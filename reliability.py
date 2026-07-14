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
trades. There are no eligibility gates, Wilson bounds, or recovery-time
statistics: per-dip "time to recover" is ill-defined when dips overlap, and
everything subjective is left to the chart explorer.

Pure functions only (no network) so the math is unit-testable in isolation.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

DEFAULT_RECENT_WINDOW_DAYS = 30

# Signal = direction of the latest threshold event, nothing more. A down leg
# means price sits -N% from the last anchor (a dip you could buy); an up leg
# means a +N% move just completed (a harvest you could sell). Whether to act
# is the investor's decision — there is no position tracking anywhere.
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


def compute_oscillation_summary(prices: pd.DataFrame,
                                threshold_pct: float = 10.0,
                                as_of: date | None = None,
                                recent_window_days: int = DEFAULT_RECENT_WINDOW_DAYS) -> dict:
    """One ticker's oscillation summary over the supplied price window.

    Parameters
    ----------
    prices : DataFrame with columns ['date', 'close'], ascending by date.
    threshold_pct : the +/-N% move that defines one leg.
    as_of : anchor date for the recent-events window (default: the last price
        date, so the output is stable regardless of when it is viewed).

    Returns a dict with the leg counts, ``up_legs_per_year`` (the ranking key:
    completed +N% recoveries per year of data), ``trend_positive`` (drift
    filter), CAGR / max-drawdown context, the current streak, the stateless
    BUY/SELL signal derived from the latest event, and ``recent_events``
    (every event in the trailing ``recent_window_days``, oldest first).
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
        "trend_positive": False,
        "current_streak": 0,
        "last_event_date": None,
        "signal": SIGNAL_NONE,
        "signal_price": None,
        "pct_since_signal": None,
        "recent_events": [],
    }

    if prices is None or len(prices) < 2:
        return out

    prices = prices.reset_index(drop=True).copy()
    prices["date"] = pd.to_datetime(prices["date"], format="mixed", dayfirst=False)
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

    window_start = as_of - timedelta(days=recent_window_days)
    in_window = ev[(ev["date"].dt.date > window_start) & (ev["date"].dt.date <= as_of)]
    out["recent_events"] = [
        {"date": d.strftime("%Y-%m-%d"), "direction": dirn}
        for d, dirn in zip(in_window["date"], in_window["direction"])
    ]
    return out
