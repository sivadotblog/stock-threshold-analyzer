"""
Cost-aware walk-forward backtest of the dip-buy loop (spec §4) and the shared
day-step trade engine that also powers the live signal states (spec §5.5).

Strategy (all decisions use only data known at the time):
* **Universe as-of**: on the first trading day of each month, rank every ticker
  by ``bounce_rate_wilson_low`` computed as of that close; the top K form the
  watchlist.
* **Entry**: a watchlist ticker printing a -N% down-trigger at close t is a
  ``BUY_SETUP``; the position is opened at the *next* trading day's open
  (a trigger is only knowable at the close — never same-bar).
* **Exit**: first of +N% recovery above the trigger close (checked at close,
  filled next open), a resting hard stop at ``stop_mae_mult x median MAE``
  below the trigger (filled intraday at the stop, or at the open on a gap), or
  a ``max_hold_days`` calendar time stop (filled next open).
* **Sizing**: equal-weight slots of equity/max_positions, fixed fractional, so
  gains compound.
* **Costs**: per-side slippage+spread in bps plus optional flat commission.
* **Taxes**: optional short-term rate applied annually to net realized gains
  (with loss carryforward), paid out of account cash — so the after-tax run
  compounds less. Pre-tax and after-tax are two runs of the same engine.

The engine emits a signal record for every state transition; ``signals.py``
replays the same engine, which is what keeps the live indicator honest
(enforced by the signal/backtest parity test).

Pure functions on DataFrames; I/O (fetching, CSV writing) lives in the CLI.
Determinism: ties in ranking and entry order break on ticker symbol.
"""

from __future__ import annotations

import math
from typing import Callable, Optional

import numpy as np
import pandas as pd

from metrics import compute_bounce_metrics

# Signal states (spec §5.5). SUPPRESSED/NONE are presentation-layer states
# applied in signals.py; the engine emits the raw mechanical states below.
BUY_SETUP = "BUY_SETUP"
IN_TRADE = "IN_TRADE"
SELL_RECOVERY = "SELL_RECOVERY"
SELL_STOP = "SELL_STOP"
SELL_TIME = "SELL_TIME"

END_OF_PERIOD = "end_of_period"  # accounting-only exit reason


def rank_asof(events_by_ticker: dict[str, pd.DataFrame], as_of, cfg: dict) -> pd.DataFrame:
    """Rank the universe by ``bounce_rate_wilson_low`` using only data <= as_of.

    A ticker is rankable when it has at least ``min_events_asof`` *resolved*
    down events and a median MAE (needed to place the stop). Ties break on
    ticker symbol for determinism.
    """
    rows = []
    for ticker in sorted(events_by_ticker):
        m = compute_bounce_metrics(
            events_by_ticker[ticker], as_of=as_of,
            threshold_pct=cfg["threshold_pct"],
            window_years=cfg["window_years"],
            low_sample_min_events=cfg["low_sample_min_events"])
        if (m["n_bounces"] + m["n_continuations"] >= cfg["min_events_asof"]
                and m["median_mae_pct"] is not None):
            m["ticker"] = ticker
            rows.append(m)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values(
        ["bounce_rate_wilson_low", "ticker"], ascending=[False, True])
    return df.reset_index(drop=True)


def _down_events_by_date(events: pd.DataFrame) -> dict[pd.Timestamp, float]:
    """date -> trigger close for every down event of one ticker."""
    ev = events[events["direction"] == "down"]
    return dict(zip(ev["date"], ev["price"].astype(float)))


def run_engine(events_by_ticker: dict[str, pd.DataFrame],
               ohlc_loader: Callable[[str], Optional[pd.DataFrame]],
               calendar: pd.DatetimeIndex,
               cfg: dict,
               tax_rate: float = 0.0) -> dict:
    """Walk the calendar day by day, emitting signals and executing trades.

    Parameters
    ----------
    events_by_ticker : full-history event frames (``events.build_events``);
        as-of censoring happens inside the metric calls.
    ohlc_loader : ticker -> DataFrame['date','open','high','low','close'] or
        None. Called lazily for tickers that enter the watchlist.
    calendar : the master trading calendar (e.g. SPY's dates) clipped to the
        backtest period.
    tax_rate : short-term rate applied annually to net realized gains, paid
        from cash (0.0 = pre-tax run).

    Returns dict with ``trades`` / ``signals`` / ``skipped_entries`` records,
    the daily ``equity_curve``, and end-of-run ``positions`` / ``watchlist``
    for the live signal view.
    """
    bps = cfg["cost_bps_per_side"] / 1e4
    commission = cfg["commission_per_trade"]
    recovery_mult = 1.0 + cfg["threshold_pct"] / 100.0

    cash = float(cfg["starting_cash"])
    positions: dict[str, dict] = {}
    pending_entries: list[dict] = []
    pending_exits: list[dict] = []
    watchlist: dict[str, dict] = {}
    down_by_date: dict[str, dict] = {
        t: _down_events_by_date(ev) for t, ev in events_by_ticker.items()}

    ohlc_cache: dict[str, Optional[pd.DataFrame]] = {}

    def bars(ticker: str) -> Optional[pd.DataFrame]:
        if ticker not in ohlc_cache:
            df = ohlc_loader(ticker)
            if df is not None:
                df = df.copy()
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date").sort_index()
            ohlc_cache[ticker] = df
        return ohlc_cache[ticker]

    trades: list[dict] = []
    signals: list[dict] = []
    skipped: list[dict] = []
    equity_rows: list[dict] = []
    last_close: dict[str, float] = {}
    buy_notional = 0.0
    invested_frac_sum = 0.0

    realized_by_year: dict[int, float] = {}
    loss_carry = 0.0
    taxes_paid = 0.0

    def mark_equity() -> float:
        return cash + sum(p["shares"] * last_close.get(t, p["entry_price"])
                          for t, p in positions.items())

    def close_position(ticker: str, fill_raw: float, day, reason: str):
        nonlocal cash
        p = positions.pop(ticker)
        proceeds = p["shares"] * fill_raw * (1.0 - bps) - commission
        cash += proceeds
        realized = proceeds - p["cost_basis"]
        realized_by_year[day.year] = realized_by_year.get(day.year, 0.0) + realized
        trades.append({
            "ticker": ticker,
            "trigger_date": p["trigger_date"], "trigger_price": p["trigger_price"],
            "entry_date": p["entry_date"], "entry_price": round(p["entry_fill"], 4),
            "exit_date": day, "exit_price": round(fill_raw * (1.0 - bps), 4),
            "exit_reason": reason,
            "days_held": int((day - p["entry_date"]).days),
            "shares": round(p["shares"], 6),
            "pnl_usd": round(realized, 2),
            "pnl_pct": round(realized / p["cost_basis"] * 100.0, 4),
        })

    prev_equity = cash
    rebalance_month = None

    for day in calendar:
        # --- yearly tax settlement on the first trading day of a new year ---
        if tax_rate > 0 and equity_rows and day.year != equity_rows[-1]["date"].year:
            prev_year = equity_rows[-1]["date"].year
            taxable = realized_by_year.get(prev_year, 0.0) - loss_carry
            if taxable > 0:
                tax = tax_rate * taxable
                cash -= tax
                taxes_paid += tax
                loss_carry = 0.0
            else:
                loss_carry = -taxable

        # --- 1. execute pending exits at today's open ---
        for pe in pending_exits:
            ticker = pe["ticker"]
            if ticker not in positions:
                continue
            b = bars(ticker)
            if b is None or day not in b.index:
                continue  # halted: retry next day
            close_position(ticker, float(b.at[day, "open"]), day, pe["reason"])
        pending_exits = [pe for pe in pending_exits if pe["ticker"] in positions]

        # --- 2. execute pending entries at today's open ---
        for en in sorted(pending_entries,
                         key=lambda e: (-e["wilson"], e["ticker"])):
            ticker = en["ticker"]
            if ticker in positions:
                continue
            if len(positions) >= cfg["max_positions"]:
                skipped.append({**en, "skip_reason": "no_slot", "skip_date": day})
                continue
            b = bars(ticker)
            if b is None or day not in b.index:
                skipped.append({**en, "skip_reason": "no_data", "skip_date": day})
                continue
            open_px = float(b.at[day, "open"])
            fill = open_px * (1.0 + bps)
            slot = min(prev_equity / cfg["max_positions"], cash - commission)
            if slot <= 0 or fill <= 0:
                skipped.append({**en, "skip_reason": "no_cash", "skip_date": day})
                continue
            shares = slot / fill
            cash -= shares * fill + commission
            buy_notional += shares * fill
            positions[ticker] = {
                "shares": shares,
                "entry_date": day, "entry_fill": fill, "entry_price": fill,
                "cost_basis": shares * fill + commission,
                "trigger_date": en["trigger_date"],
                "trigger_price": en["trigger_price"],
                "stop_price": en["stop_price"],
                "recovery_price": en["trigger_price"] * recovery_mult,
                "median_days_to_bounce": en.get("median_days_to_bounce"),
            }
        pending_entries = []

        # --- 3. intraday resting-stop check (includes today's entries:
        #        pessimistic when the low printed before the entry fill) ---
        for ticker in sorted(positions):
            p = positions[ticker]
            b = bars(ticker)
            if b is None or day not in b.index:
                continue
            row = b.loc[day]
            last_close[ticker] = float(row["close"])
            if float(row["low"]) <= p["stop_price"]:
                fill_raw = min(float(row["open"]), p["stop_price"])
                signals.append({"date": day, "ticker": ticker, "state": SELL_STOP,
                                "price": round(fill_raw, 4)})
                close_position(ticker, fill_raw, day, SELL_STOP)

        # --- 4. close-of-day exit decisions (executed next open) ---
        pending_names = {pe["ticker"] for pe in pending_exits}
        for ticker in sorted(positions):
            if ticker in pending_names:
                continue
            p = positions[ticker]
            c = last_close.get(ticker)
            if c is None:
                continue
            if c >= p["recovery_price"]:
                signals.append({"date": day, "ticker": ticker,
                                "state": SELL_RECOVERY, "price": c})
                pending_exits.append({"ticker": ticker, "reason": SELL_RECOVERY})
            elif (day - p["entry_date"]).days >= cfg["max_hold_days"]:
                signals.append({"date": day, "ticker": ticker,
                                "state": SELL_TIME, "price": c})
                pending_exits.append({"ticker": ticker, "reason": SELL_TIME})

        # --- 5. monthly rebalance at the close (data <= today only) ---
        if rebalance_month != (day.year, day.month):
            rebalance_month = (day.year, day.month)
            ranked = rank_asof(events_by_ticker, day, cfg)
            watchlist = {}
            if not ranked.empty:
                for _, r in ranked.head(cfg["top_k"]).iterrows():
                    watchlist[r["ticker"]] = r.to_dict()

        # --- 6. new down-triggers on watchlist tickers -> BUY_SETUP ---
        exiting = {pe["ticker"] for pe in pending_exits}
        for ticker in sorted(watchlist):
            if ticker in positions or ticker in exiting:
                continue
            trig = down_by_date.get(ticker, {}).get(day)
            if trig is None:
                continue
            w = watchlist[ticker]
            stop_price = trig * (1.0 - cfg["stop_mae_mult"] * w["median_mae_pct"] / 100.0)
            setup = {
                "ticker": ticker, "trigger_date": day, "trigger_price": trig,
                "stop_price": round(stop_price, 4),
                "wilson": w["bounce_rate_wilson_low"],
                "bounce_rate": w["bounce_rate"],
                "n_down_events": w["n_down_events"],
                "median_days_to_bounce": w["median_days_to_bounce"],
                "p90_days_to_bounce": w["p90_days_to_bounce"],
                "median_mae_pct": w["median_mae_pct"],
                "low_sample": w["low_sample"],
            }
            signals.append({"date": day, "ticker": ticker, "state": BUY_SETUP,
                            "price": trig, **{k: v for k, v in setup.items()
                                              if k not in ("ticker", "trigger_date",
                                                           "trigger_price")}})
            pending_entries.append(setup)

        # --- 7. mark equity at the close ---
        for ticker, p in positions.items():
            b = bars(ticker)
            if b is not None and day in b.index:
                last_close[ticker] = float(b.at[day, "close"])
        equity = mark_equity()
        invested_frac_sum += (equity - cash) / equity if equity > 0 else 0.0
        equity_rows.append({"date": day, "equity": equity})
        prev_equity = equity

    # --- final accounting: force-close open positions at the last close ---
    open_positions_snapshot = {
        t: {**p, "days_held": int((calendar[-1] - p["entry_date"]).days)}
        for t, p in positions.items()}
    for ticker in sorted(positions):
        fill = last_close.get(ticker, positions[ticker]["entry_price"])
        close_position(ticker, fill, calendar[-1], END_OF_PERIOD)
    if equity_rows:
        equity_rows[-1]["equity"] = cash

    # final-year tax settlement (reporting)
    if tax_rate > 0:
        last_year = calendar[-1].year
        taxable = realized_by_year.get(last_year, 0.0) - loss_carry
        if taxable > 0:
            tax = tax_rate * taxable
            cash -= tax
            taxes_paid += tax
            equity_rows[-1]["equity"] = cash

    n_days = len(calendar)
    return {
        "trades": pd.DataFrame(trades),
        "signals": pd.DataFrame(signals),
        "skipped_entries": pd.DataFrame(skipped),
        "equity_curve": pd.DataFrame(equity_rows),
        "positions": open_positions_snapshot,
        "watchlist": watchlist,
        "buy_notional": buy_notional,
        "exposure": invested_frac_sum / n_days if n_days else 0.0,
        "taxes_paid": round(taxes_paid, 2),
    }


def _cagr(first: float, last: float, days: int) -> float:
    years = days / 365.25
    if years <= 0 or first <= 0 or last <= 0:
        return 0.0
    return (last / first) ** (1.0 / years) - 1.0


def _path_max_drawdown(values: np.ndarray) -> float:
    """Worst peak-to-trough drawdown of a value path, as a fraction <= 0."""
    running_max = np.maximum.accumulate(values)
    return float(((values - running_max) / running_max).min())


def _buy_and_hold(ohlc: pd.DataFrame, calendar: pd.DatetimeIndex) -> Optional[pd.Series]:
    """Close-price path of 1 unit bought at the first open of the period."""
    df = ohlc.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df[(df.index >= calendar[0]) & (df.index <= calendar[-1])]
    if df.empty:
        return None
    units = 1.0 / float(df.iloc[0]["open"])
    return df["close"] * units


def summarize(result: dict, calendar: pd.DatetimeIndex,
              spy_ohlc: Optional[pd.DataFrame] = None,
              benchmark_ohlc: Optional[dict[str, pd.DataFrame]] = None) -> dict:
    """Boil an engine run down to the §4 report block."""
    eq = result["equity_curve"]
    days = int((calendar[-1] - calendar[0]).days)
    values = eq["equity"].to_numpy(dtype=float)
    trades = result["trades"]
    real_trades = trades[trades["exit_reason"] != END_OF_PERIOD] if len(trades) else trades

    wins = real_trades[real_trades["pnl_usd"] > 0] if len(real_trades) else real_trades
    losses = real_trades[real_trades["pnl_usd"] <= 0] if len(real_trades) else real_trades

    years = days / 365.25
    avg_equity = float(values.mean()) if len(values) else 0.0
    out = {
        "period": [str(calendar[0].date()), str(calendar[-1].date())],
        "cagr_pct": round(_cagr(values[0], values[-1], days) * 100, 2),
        "max_drawdown_pct": round(_path_max_drawdown(values) * 100, 2),
        "n_trades": int(len(real_trades)),
        "n_forced_close": int(len(trades) - len(real_trades)),
        "hit_rate": round(len(wins) / len(real_trades), 4) if len(real_trades) else None,
        "avg_win_pct": round(float(wins["pnl_pct"].mean()), 3) if len(wins) else None,
        "avg_loss_pct": round(float(losses["pnl_pct"].mean()), 3) if len(losses) else None,
        "exposure_pct": round(result["exposure"] * 100, 1),
        "turnover_x_per_year": round(
            result["buy_notional"] / avg_equity / years, 2)
            if avg_equity > 0 and years > 0 else None,
        "taxes_paid": result["taxes_paid"],
        "final_equity": round(values[-1], 2) if len(values) else None,
    }

    if spy_ohlc is not None:
        path = _buy_and_hold(spy_ohlc, calendar)
        if path is not None:
            v = path.to_numpy(dtype=float)
            out["benchmark_spy"] = {
                "cagr_pct": round(_cagr(v[0], v[-1], days) * 100, 2),
                "max_drawdown_pct": round(_path_max_drawdown(v) * 100, 2),
            }

    if benchmark_ohlc:
        paths = []
        for t, ohlc in sorted(benchmark_ohlc.items()):
            p = _buy_and_hold(ohlc, calendar)
            if p is not None:
                paths.append(p / p.iloc[0])
        if paths:
            ew = pd.concat(paths, axis=1).ffill().mean(axis=1).dropna()
            v = ew.to_numpy(dtype=float)
            out["benchmark_equal_weight"] = {
                "n_tickers": len(paths),
                "cagr_pct": round(_cagr(v[0], v[-1], days) * 100, 2),
                "max_drawdown_pct": round(_path_max_drawdown(v) * 100, 2),
            }
    return out


def sensitivity_grid(prices_by_ticker: dict[str, pd.DataFrame],
                     ohlc_loader: Callable[[str], Optional[pd.DataFrame]],
                     calendar: pd.DatetimeIndex,
                     base_cfg: dict, grid: dict) -> pd.DataFrame:
    """Re-run the pre-tax backtest over a small N x stop x hold grid.

    One good cell surrounded by bad neighbors means the base parameters are
    overfit — print and eyeball, don't cherry-pick.
    """
    from events import build_events

    rows = []
    for n in grid["thresholds_pct"]:
        events_by_ticker = {
            t: build_events(p, n) for t, p in prices_by_ticker.items()}
        for stop_mult in grid["stop_mae_mult"]:
            for hold in grid["max_hold_days"]:
                cfg = {**base_cfg, "threshold_pct": n,
                       "stop_mae_mult": stop_mult, "max_hold_days": hold}
                res = run_engine(events_by_ticker, ohlc_loader, calendar, cfg)
                rep = summarize(res, calendar)
                rows.append({
                    "threshold_pct": n, "stop_mae_mult": stop_mult,
                    "max_hold_days": hold,
                    "cagr_pct": rep["cagr_pct"],
                    "max_drawdown_pct": rep["max_drawdown_pct"],
                    "n_trades": rep["n_trades"],
                    "hit_rate": rep["hit_rate"],
                })
    return pd.DataFrame(rows)
