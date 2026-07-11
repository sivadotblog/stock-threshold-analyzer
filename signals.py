"""
Live per-ticker entry/exit states (spec §5.5), derived from the SAME day-step
engine as the backtest (``backtest.run_engine``) — the signal/backtest parity
test asserts they can never drift apart.

States:
* ``BUY_SETUP``      — latest close printed a -N% trigger on a current top-K
                       ticker.
* ``IN_TRADE``       — a prior BUY_SETUP is still unresolved.
* ``SELL_RECOVERY``  / ``SELL_STOP`` / ``SELL_TIME`` — mechanical exits.
* ``NONE``           — watchlist ticker with no active trigger.
* ``SUPPRESSED``     — the mechanical signal exists but the row is
                       low-sample (n_down_events < low_sample_min_events):
                       greyed reason, never an actionable state.

NOTE: the §3 cross-sectional validation status (PASSED/WEAK/FAILED) is no
longer used to gate signals here. That test pools the *entire* universe into
one Spearman correlation, which can mask a real, sector-specific persistence
pattern (a heterogeneous pool of e.g. oil + growth + leveraged names can fail
even if a coherent subgroup would pass) — see README "Validation" section.
``validation_status`` is still threaded through and attached to every row for
display/diagnostic purposes; a sector-stratified validation harness that could
legitimately gate signals is a planned follow-up, not implemented yet.

Every emitted row carries its historical base rate ("bounced 41/52, Wilson low
0.68") — this is a base-rate display, not a prediction.

Pure functions; the CLI owns I/O (including appending output/signals_log.csv
so live signal quality can later be compared with the backtest's expectations).
"""

from __future__ import annotations

import pandas as pd

from backtest import BUY_SETUP, IN_TRADE, SELL_RECOVERY, SELL_STOP, SELL_TIME

NONE_STATE = "NONE"
SUPPRESSED = "SUPPRESSED"

ACTIONABLE = {BUY_SETUP, IN_TRADE, SELL_RECOVERY, SELL_STOP, SELL_TIME}


def _base_rate(w: dict) -> str:
    n_res = int(w.get("n_bounces", 0)) + int(w.get("n_continuations", 0))
    return (f"bounced {int(w.get('n_bounces', 0))}/{n_res} times, "
            f"95% Wilson low {w.get('bounce_rate_wilson_low', 0):.2f}")


def _next_trading_day(as_of: pd.Timestamp) -> pd.Timestamp:
    """Next US business day — triggers are only knowable at the close, so a
    signal is actionable from the NEXT open, never same-day."""
    return (as_of + pd.tseries.offsets.BDay(1)).normalize()


def evaluate_states(engine_result: dict,
                    as_of: pd.Timestamp,
                    cfg: dict,
                    validation_status: str) -> list[dict]:
    """Convert an engine run into the §5.5 state rows at ``as_of``.

    ``engine_result`` is ``backtest.run_engine`` output over a calendar ending
    at ``as_of``. Suppression (the low-sample gate) happens here, in the
    presentation layer — the engine stays purely mechanical.
    ``validation_status`` is attached to every row for display only; it does
    NOT suppress signals (see module docstring).
    """
    as_of = pd.Timestamp(as_of)
    actionable_from = _next_trading_day(as_of)
    watchlist: dict = engine_result["watchlist"]
    positions: dict = engine_result["positions"]
    signals = engine_result["signals"]
    today = (signals[signals["date"] == as_of]
             if len(signals) else pd.DataFrame(columns=["ticker", "state"]))
    today_by_ticker = {r["ticker"]: r for _, r in today.iterrows()}

    rows: list[dict] = []
    tickers = sorted(set(watchlist) | set(positions) | set(today_by_ticker))

    for ticker in tickers:
        w = watchlist.get(ticker, {})
        row: dict = {
            "date": str(as_of.date()),
            "ticker": ticker,
            "state": NONE_STATE,
            "validation_status": validation_status,
            "base_rate": _base_rate(w) if w else None,
            "low_sample": bool(w.get("low_sample", False)) if w else None,
        }

        if ticker in positions:
            p = positions[ticker]
            row.update(
                state=IN_TRADE,
                trigger_date=str(pd.Timestamp(p["trigger_date"]).date()),
                trigger_price=round(float(p["trigger_price"]), 4),
                entry_date=str(pd.Timestamp(p["entry_date"]).date()),
                entry_price=round(float(p["entry_price"]), 4),
                days_held=int(p["days_held"]),
                median_days_to_bounce=p.get("median_days_to_bounce"),
                stop_price=round(float(p["stop_price"]), 4),
                time_stop_date=str(
                    (pd.Timestamp(p["entry_date"])
                     + pd.Timedelta(days=cfg["max_hold_days"])).date()),
            )
            sig = today_by_ticker.get(ticker)
            if sig is not None and sig["state"] in (SELL_RECOVERY, SELL_STOP, SELL_TIME):
                row["state"] = sig["state"]
                row["exit_actionable_from"] = str(actionable_from.date())
        elif ticker in today_by_ticker:
            sig = today_by_ticker[ticker]
            if sig["state"] == BUY_SETUP:
                # Full context, not just a badge (spec §5.5).
                row.update(
                    state=BUY_SETUP,
                    trigger_date=str(as_of.date()),
                    trigger_price=round(float(sig["price"]), 4),
                    actionable_from=str(actionable_from.date()),
                    bounce_rate=w.get("bounce_rate"),
                    bounce_rate_wilson_low=w.get("bounce_rate_wilson_low"),
                    n_down_events=w.get("n_down_events"),
                    median_days_to_bounce=w.get("median_days_to_bounce"),
                    p90_days_to_bounce=w.get("p90_days_to_bounce"),
                    stop_price=sig.get("stop_price"),
                    time_stop_date=str(
                        (actionable_from
                         + pd.Timedelta(days=cfg["max_hold_days"])).date()),
                    # "expect it to typically get worse before resolving"
                    median_mae_pct=w.get("median_mae_pct"),
                )
            else:  # a SELL on a position force-closed same day; keep the record
                row["state"] = sig["state"]

        # --- low-sample gate: suppress a BUY_SETUP with too thin a track
        # record. (The universe-wide validation status is informational only
        # — see module docstring — and does not suppress signals.) ---
        if row["state"] in ACTIONABLE:
            reasons = []
            if row["state"] == BUY_SETUP and row.get("low_sample"):
                reasons.append(
                    f"low sample (n={w.get('n_down_events')} down events)")
            if reasons:
                row["underlying_state"] = row["state"]
                row["state"] = SUPPRESSED
                row["suppressed_reason"] = "; ".join(reasons)

        rows.append(row)
    return rows
