"""
Anchor-reset threshold events and the per-ticker oscillation summary.

The rule: start at the first close as the anchor; every time the close moves
+/- threshold_pct from the current anchor, log an event and reset the anchor
to that close.

The summary is deliberately descriptive, not a composite score. The goal is
dip-cycle compounding: a ticker that prints many +/-N% legs while net-trending
up offers many +N% harvests per year. What matters is:

  * how many POSITIVE oscillations it actually printed (``up_legs_per_year``
    — each completed +N% leg is one harvestable recovery),
  * that the drift over the window is positive (``trend_positive`` — a
    down-trender is excluded no matter how nicely it swings),
  * context: CAGR (growth) and max drawdown (volatility).

Consecutive down legs are never treated as failures — a stock that fell -10%
three times and then recovered is oscillation richness, not three failed
trades. There are no Wilson bounds or recovery-time statistics: per-dip "time
to recover" is ill-defined when dips overlap, and everything subjective is
left to the chart explorer.

One deliberate gate exists besides the trend filter: the *parabolic* flag.
A ticker that spiked (e.g. 3x+) from its trailing 12-month low anywhere in
the window (CIFR $3 -> $25) prints lots of legs from a one-way regime shift,
not a repeatable dip-cycle — its oscillation history is unreliable, so it is
flagged (``parabolic``) and ranked below steady oscillators like QQQ/SPY.
``max_run_up_pct`` (the largest gain from any trailing-window low) is always
reported so the evidence behind the flag is never hidden.

Pure functions only (no network) so the math is unit-testable in isolation.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

DEFAULT_RECENT_WINDOW_DAYS = 30
DEFAULT_PARABOLIC_WINDOW_DAYS = 365
DEFAULT_PARABOLIC_MAX_RUN_UP_PCT = 200.0

# The LAST signal = direction of the latest threshold event, nothing more. A
# down leg means price printed -N% from the last anchor (a dip you could buy);
# an up leg means a +N% move completed (a harvest you could sell). It is not a
# realtime state: it stays what it was until the next event fires. Whether to
# act is the investor's decision — there is no position tracking anywhere.
SIGNAL_BUY = "BUY"
SIGNAL_SELL = "SELL"
SIGNAL_NONE = "NONE"

_DAYS_PER_YEAR = 365.25
_EPS = 1e-9


def find_threshold_events(df: pd.DataFrame, threshold_pct: float) -> pd.DataFrame:
    """Walk the price series and emit an event every time price moves
    +/- threshold_pct from the current anchor, then reset the anchor.
    """
    anchor_price = float(df.loc[0, "close"])
    anchor_date = df.loc[0, "date"]

    events: list[dict] = [{
        "date": anchor_date,
        "price": anchor_price,
        "direction": "start",
        "pct_from_anchor": 0.0,
    }]

    for i in range(1, len(df)):
        price = float(df.loc[i, "close"])
        date = df.loc[i, "date"]
        pct = (price - anchor_price) / anchor_price * 100

        if pct >= threshold_pct:
            events.append({
                "date": date, "price": price,
                "direction": "up", "pct_from_anchor": pct,
            })
            anchor_price = price
        elif pct <= -threshold_pct:
            events.append({
                "date": date, "price": price,
                "direction": "down", "pct_from_anchor": pct,
            })
            anchor_price = price

    return pd.DataFrame(events)


def _cagr_and_max_drawdown(close: np.ndarray, span_days: int) -> tuple[float, float]:
    """Annualized return and worst peak-to-trough drawdown (both as fractions).

    ``max_drawdown`` is <= 0 (e.g. -0.42 = a 42% drawdown).
    """
    cagr = 0.0
    years = span_days / _DAYS_PER_YEAR
    if years > _EPS and close[0] > _EPS:
        cagr = float((close[-1] / close[0]) ** (1.0 / years) - 1.0)
    running_max = np.maximum.accumulate(close)
    max_drawdown = float(((close - running_max) / running_max).min())
    return cagr, max_drawdown


def _max_run_up(prices: pd.DataFrame, window_days: int) -> float:
    """Largest % gain from the lowest close in any trailing ``window_days``
    window: max over t of close[t] / min(close[t-window .. t]) - 1, as a
    percentage. Daily closes, no averaging — catches a spike anywhere in the
    lookback even if it later plateaued or retraced.
    """
    closes = pd.Series(prices["close"].to_numpy(dtype=float),
                       index=pd.DatetimeIndex(prices["date"]))
    # Some cached feeds deliver out-of-order rows; time-based rolling demands
    # a monotonic index.
    closes = closes.sort_index()
    rolling_low = closes.rolling(f"{window_days}D").min()
    ratio = (closes / rolling_low).max()
    if not np.isfinite(ratio):
        return 0.0
    return float((ratio - 1.0) * 100)


def compute_oscillation_summary(prices: pd.DataFrame,
                                threshold_pct: float = 10.0,
                                as_of: date | None = None,
                                recent_window_days: int = DEFAULT_RECENT_WINDOW_DAYS,
                                parabolic_window_days: int = DEFAULT_PARABOLIC_WINDOW_DAYS,
                                parabolic_max_run_up_pct: float = DEFAULT_PARABOLIC_MAX_RUN_UP_PCT) -> dict:
    """One ticker's oscillation summary over the supplied price window.

    Parameters
    ----------
    prices : DataFrame with columns ['date', 'close'], ascending by date.
    threshold_pct : the +/-N% move that defines one leg.
    as_of : anchor date for the recent-events window (default: the last price
        date, so the output is stable regardless of when it is viewed).

    Returns a dict with the leg counts, ``up_legs_per_year`` (the ranking key:
    completed +N% recoveries per year of data), ``trend_positive`` (drift
    filter), ``max_run_up_pct`` / ``parabolic`` (spike gate: largest gain from
    a trailing ``parabolic_window_days`` low; flagged when it reaches
    ``parabolic_max_run_up_pct``), CAGR / max-drawdown context, the current
    streak, the last and
    previous signals (direction/date/price of the latest two events — these
    are history, not realtime states), ``target_price`` (where the opposite
    signal would fire: a BUY at 100 harvests at SELL >= 110), and
    ``recent_events`` (every event in the trailing window, oldest first).
    """
    out = {
        "n_up": 0,
        "n_down": 0,
        "n_events": 0,
        "up_legs_per_year": 0.0,
        "span_years": 0.0,
        "net_return_pct": 0.0,
        "cagr_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "max_run_up_pct": 0.0,
        "parabolic": False,
        "trend_positive": False,
        "current_streak": 0,
        "last_event_date": None,
        "signal": SIGNAL_NONE,
        "signal_price": None,
        "pct_since_signal": None,
        "target_side": None,
        "target_price": None,
        "prev_signal": None,
        "prev_signal_date": None,
        "prev_signal_price": None,
        "recent_events": [],
    }

    if prices is None or len(prices) < 2:
        return out

    prices = prices.reset_index(drop=True).copy()
    prices["date"] = pd.to_datetime(prices["date"], format="mixed", dayfirst=False)
    # NaN closes (half-formed Yahoo bars, stale caches) would poison every stat.
    prices = prices.dropna(subset=["close"]).reset_index(drop=True)
    if len(prices) < 2:
        return out
    as_of = as_of or prices["date"].iloc[-1].date()

    events = find_threshold_events(prices, threshold_pct)
    ev = events[events["direction"].isin(["up", "down"])].reset_index(drop=True)

    n_up = int((ev["direction"] == "up").sum())
    n_down = int((ev["direction"] == "down").sum())
    out.update(n_up=n_up, n_down=n_down, n_events=n_up + n_down)

    close = prices["close"].to_numpy(dtype=float)
    net_return = float((close[-1] - close[0]) / close[0])
    out["net_return_pct"] = round(net_return * 100, 2)

    span_days = (prices["date"].iloc[-1] - prices["date"].iloc[0]).days
    span_years = span_days / _DAYS_PER_YEAR
    out["span_years"] = round(span_years, 2)
    if span_years > _EPS:
        out["up_legs_per_year"] = round(n_up / span_years, 2)

    cagr, max_dd = _cagr_and_max_drawdown(close, span_days)
    out["cagr_pct"] = round(cagr * 100, 2)
    out["max_drawdown_pct"] = round(max_dd * 100, 2)
    out["trend_positive"] = bool(net_return > 0)

    run_up = _max_run_up(prices, parabolic_window_days)
    out["max_run_up_pct"] = round(run_up, 2)
    out["parabolic"] = bool(run_up >= parabolic_max_run_up_pct)

    if len(ev):
        dirs = ev["direction"].tolist()
        last_dir = dirs[-1]
        streak = 0
        for d in reversed(dirs):
            if d == last_dir:
                streak += 1
            else:
                break
        out["current_streak"] = streak if last_dir == "up" else -streak

        last = ev.iloc[-1]
        out["last_event_date"] = last["date"].strftime("%Y-%m-%d")
        out["signal"] = SIGNAL_BUY if last_dir == "down" else SIGNAL_SELL
        signal_price = float(last["price"])
        out["signal_price"] = round(signal_price, 4)
        out["pct_since_signal"] = round(
            (close[-1] - signal_price) / signal_price * 100, 2)

        # Where the opposite signal fires: a BUY at 100 harvests at SELL >= 110;
        # a SELL at 110 sets the next dip trigger at BUY <= 99.
        if out["signal"] == SIGNAL_BUY:
            out["target_side"] = SIGNAL_SELL
            out["target_price"] = round(signal_price * (1 + threshold_pct / 100), 4)
        else:
            out["target_side"] = SIGNAL_BUY
            out["target_price"] = round(signal_price * (1 - threshold_pct / 100), 4)

        if len(ev) >= 2:
            prev = ev.iloc[-2]
            out["prev_signal"] = (SIGNAL_BUY if prev["direction"] == "down"
                                  else SIGNAL_SELL)
            out["prev_signal_date"] = prev["date"].strftime("%Y-%m-%d")
            out["prev_signal_price"] = round(float(prev["price"]), 4)

    window_start = as_of - timedelta(days=recent_window_days)
    in_window = ev[(ev["date"].dt.date > window_start) & (ev["date"].dt.date <= as_of)]
    out["recent_events"] = [
        {"date": d.strftime("%Y-%m-%d"), "direction": dirn}
        for d, dirn in zip(in_window["date"], in_window["direction"])
    ]
    return out
