"""
Anchor-reset threshold events and the per-ticker oscillation summary.

The rule: start at the first close as the anchor; every time the close moves
+/- threshold_pct from the current anchor, log an event and reset the anchor
to that close.

The summary is deliberately descriptive, not a composite score. The goal is
dip-cycle compounding: a ticker that prints many +/-N% legs while net-trending
up offers many +N% harvests per year. What matters is:

  * the SURPLUS of harvests over dips (``net_legs_per_year`` — the ranking
    key: (n_up - n_down) / span_years. Two things make an oscillator good:
    a favorable up/down ratio (quality) and a high leg count (frequency) —
    neither alone is enough. VICI's ratio is fine (10 up / 8 down = 1.25x)
    but it barely moves (0.4 net legs/yr); SPXL's ratio is worse (1.44x)
    but it moves constantly (2.8 net legs/yr) and still lands ahead of
    VICI. The subtraction is the fusion: every up leg is a harvest, every
    down leg is capital committed, and the difference per year is how fast
    the two accumulate against each other — it is a count with units, not
    a weighted blend),
  * how RELIABLY its dips resolve (``net_dips_per_year`` / ``recovery_rate``
    — down->up transitions minus down->down, per year, and P(recovery |
    dip) — kept as context: a ticker whose dips chain a lot but still nets
    positive legs, like SPXL, is worth seeing separately from one that
    resolves cleanly, like LLY),
  * how many POSITIVE oscillations it printed (``up_legs_per_year`` — kept
    as context; ranking on it alone rewarded raw chop: MIDU hit #2 with
    nearly as many down legs as up),
  * that the drift over the window is positive (``trend_positive`` — a
    down-trender is excluded no matter how nicely it swings),
  * context: CAGR (growth) and max drawdown (volatility).

Consecutive down legs are never treated as failures — a stock that fell -10%
three times and then recovered is oscillation richness, not three failed
trades. There are no Wilson bounds or recovery-time statistics: per-dip "time
to recover" is ill-defined when dips overlap, and everything subjective is
left to the chart explorer.

Two deliberate gates exist besides the trend filter. The *parabolic* flag:
a ticker that spiked (e.g. 3x+) from its trailing 12-month low anywhere in
the window (CIFR $3 -> $25) prints lots of legs from a one-way regime shift,
not a repeatable dip-cycle — its oscillation history is unreliable, so it is
flagged (``parabolic``) and ranked below steady oscillators like QQQ/SPY.
The flag is recency-limited: only a spike inside the trailing
``parabolic_recency_days`` demotes (DIG tripled in 2022, then oscillated
cleanly for 4 years — stale evidence should not outrank fresh behavior).
``max_run_up_pct`` (the largest gain from any trailing-window low, full
window) and ``recent_run_up_pct`` (same, recency window only — the flag's
actual basis) are always reported so the evidence is never hidden.

The *chained_dips* flag: a ticker whose down legs chain deep (NET once
printed six -10% legs in a row, ~-47% compounded from the first BUY) makes
each BUY signal a weak promise — capital rides far underwater before the +10%
harvest. Flagged when the longest run of consecutive down legs reaches
``chained_max_down_streak``, or when runs of ``chained_deep_run_len``+ have
happened ``chained_deep_run_count`` or more times (depth once is an episode;
depth repeatedly is a pattern — CRWD went 4-deep twice without ever hitting
5). ``max_down_streak`` and ``deep_down_runs`` are always reported as the
evidence. Same philosophy as parabolic: gates and tiers with one visible
yes/no judgment each, never a weighted composite score.

Pure functions only (no network) so the math is unit-testable in isolation.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

DEFAULT_RECENT_WINDOW_DAYS = 30
DEFAULT_PARABOLIC_WINDOW_DAYS = 365
DEFAULT_PARABOLIC_MAX_RUN_UP_PCT = 200.0
# A spike only taints the record while it is recent: DIG tripled in the 2022
# oil rebound but has oscillated cleanly for 4 years since — flagging it until
# the episode rolls off the 5y lookback punishes stale evidence. Two years
# matches the horizon over which the leg counts are supposed to be predictive.
DEFAULT_PARABOLIC_RECENCY_DAYS = 730
# Each -N% leg compounds: at N=10 a 5-deep chain puts the first-rung BUY ~41%
# underwater before recovery (6-deep ~47%). Five is where the pain crosses
# from "scale-in richness" into "reliability problem". Depth is not the only
# axis: a ticker that goes 4-deep (~-34%) repeatedly (CRWD: twice in 5y) is a
# pattern, not an episode — one 4-deep chain (SPXL, 2022) stays clean.
DEFAULT_CHAINED_MAX_DOWN_STREAK = 5
DEFAULT_CHAINED_DEEP_RUN_LEN = 4
DEFAULT_CHAINED_DEEP_RUN_COUNT = 2
# A rate needs a denominator: QQUP ranked #16 on 8 legs from a single year of
# history. Below this many completed legs the ticker is flagged thin_history
# and sorted below every proven steady name.
DEFAULT_MIN_EVENTS = 10

# Direction labels for action_side: which side the next threshold event
# would print (BUY = the next event would be a down leg you could buy;
# SELL = the next event would be an up leg you could sell). Whether and when
# to act is the investor's decision — there is no position tracking anywhere.
SIGNAL_BUY = "BUY"
SIGNAL_SELL = "SELL"

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


def _run_up_series(prices: pd.DataFrame, window_days: int) -> pd.Series:
    """Per-day % gain over the lowest close in the trailing ``window_days``
    window: close[t] / min(close[t-window .. t]) - 1, as a percentage. Daily
    closes, no averaging — catches a spike even if it later plateaued or
    retraced. The caller decides how far back to search the series.
    """
    closes = pd.Series(prices["close"].to_numpy(dtype=float),
                       index=pd.DatetimeIndex(prices["date"]))
    # Some cached feeds deliver out-of-order rows; time-based rolling demands
    # a monotonic index.
    closes = closes.sort_index()
    rolling_low = closes.rolling(f"{window_days}D").min()
    run_up = (closes / rolling_low - 1.0) * 100
    return run_up[np.isfinite(run_up)]


def compute_oscillation_summary(prices: pd.DataFrame,
                                threshold_pct: float = 10.0,
                                as_of: date | None = None,
                                recent_window_days: int = DEFAULT_RECENT_WINDOW_DAYS,
                                parabolic_window_days: int = DEFAULT_PARABOLIC_WINDOW_DAYS,
                                parabolic_max_run_up_pct: float = DEFAULT_PARABOLIC_MAX_RUN_UP_PCT,
                                parabolic_recency_days: int = DEFAULT_PARABOLIC_RECENCY_DAYS,
                                chained_max_down_streak: int = DEFAULT_CHAINED_MAX_DOWN_STREAK,
                                chained_deep_run_len: int = DEFAULT_CHAINED_DEEP_RUN_LEN,
                                chained_deep_run_count: int = DEFAULT_CHAINED_DEEP_RUN_COUNT,
                                min_events: int = DEFAULT_MIN_EVENTS) -> dict:
    """One ticker's oscillation summary over the supplied price window.

    Parameters
    ----------
    prices : DataFrame with columns ['date', 'close'], ascending by date.
    threshold_pct : the +/-N% move that defines one leg.
    as_of : anchor date for the recent-events window (default: the last price
        date, so the output is stable regardless of when it is viewed).

    Returns a dict with the leg counts, ``net_legs_per_year`` (the ranking
    key: (n_up - n_down) / span_years — surplus of harvests over dips, so
    both a favorable up/down ratio and a high leg count are rewarded, and
    neither alone is enough), ``net_dips_per_year`` / ``recovery_rate``
    (context: dips resolved minus dips deepened per year, and P(recovery |
    dip); ``recovery_rate`` is ``None`` when there were no dips — no
    evidence is not perfection), ``up_legs_per_year`` (context: completed
    +N% recoveries per year), ``thin_history`` (fewer than ``min_events``
    completed legs — the rates have no denominator to stand on),
    ``trend_positive`` (drift filter), ``max_run_up_pct`` / ``recent_run_up_pct`` / ``parabolic`` (spike
    gate: largest gain from a trailing ``parabolic_window_days`` low; flagged
    when the recent value — within ``parabolic_recency_days`` of ``as_of`` —
    reaches ``parabolic_max_run_up_pct``), ``max_down_streak`` / ``chained_dips``
    (dip-chain gate: longest run of consecutive down legs; flagged when it
    reaches ``chained_max_down_streak``), CAGR / max-drawdown context, the
    current streak, ``current_price`` (last close), ``action_side`` /
    ``action_price`` (the next price level that would print a threshold
    event — a BUY at 100 sets the next trigger at SELL >= 110; deliberately
    not called a "signal": it is a level to compare against the current
    price, not a recommendation — whether and when to act is the investor's
    call), ``pct_to_action`` (signed % from current_price to action_price —
    negative on a BUY row, positive on a SELL row, so sorting by it surfaces
    tickers closest to their next threshold event), and ``recent_events``
    (every event in the trailing window, oldest first).
    """
    out = {
        "n_up": 0,
        "n_down": 0,
        "n_events": 0,
        "up_legs_per_year": 0.0,
        "net_legs_per_year": 0.0,
        "dips_resolved": 0,
        "dips_deepened": 0,
        "recovery_rate": None,
        "net_dips_per_year": 0.0,
        "thin_history": True,
        "span_years": 0.0,
        "net_return_pct": 0.0,
        "cagr_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "max_run_up_pct": 0.0,
        "recent_run_up_pct": 0.0,
        "parabolic": False,
        "max_down_streak": 0,
        "deep_down_runs": 0,
        "chained_dips": False,
        "trend_positive": False,
        "current_streak": 0,
        "last_event_date": None,
        "current_price": 0.0,
        "action_side": None,
        "action_price": None,
        "pct_to_action": None,
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
    out.update(n_up=n_up, n_down=n_down, n_events=n_up + n_down,
               thin_history=bool(n_up + n_down < min_events))

    close = prices["close"].to_numpy(dtype=float)
    out["current_price"] = round(float(close[-1]), 4)
    net_return = float((close[-1] - close[0]) / close[0])
    out["net_return_pct"] = round(net_return * 100, 2)

    span_days = (prices["date"].iloc[-1] - prices["date"].iloc[0]).days
    span_years = span_days / _DAYS_PER_YEAR
    out["span_years"] = round(span_years, 2)
    if span_years > _EPS:
        out["up_legs_per_year"] = round(n_up / span_years, 2)
        out["net_legs_per_year"] = round((n_up - n_down) / span_years, 2)

    cagr, max_dd = _cagr_and_max_drawdown(close, span_days)
    out["cagr_pct"] = round(cagr * 100, 2)
    out["max_drawdown_pct"] = round(max_dd * 100, 2)
    out["trend_positive"] = bool(net_return > 0)

    run_up = _run_up_series(prices, parabolic_window_days)
    if len(run_up):
        out["max_run_up_pct"] = round(float(run_up.max()), 2)
    # The flag only looks at recent spikes: an episode older than the recency
    # window stays on the record (max_run_up_pct) but no longer demotes.
    recent_cutoff = pd.Timestamp(as_of) - timedelta(days=parabolic_recency_days)
    recent = run_up[run_up.index >= recent_cutoff]
    if len(recent):
        out["recent_run_up_pct"] = round(float(recent.max()), 2)
    out["parabolic"] = bool(out["recent_run_up_pct"] >= parabolic_max_run_up_pct)

    if len(ev):
        dirs = ev["direction"].tolist()

        resolved = sum(1 for a, b in zip(dirs, dirs[1:])
                       if a == "down" and b == "up")
        deepened = sum(1 for a, b in zip(dirs, dirs[1:])
                       if a == "down" and b == "down")
        out["dips_resolved"] = resolved
        out["dips_deepened"] = deepened
        if resolved + deepened:
            out["recovery_rate"] = round(resolved / (resolved + deepened), 3)
        if span_years > _EPS:
            out["net_dips_per_year"] = round((resolved - deepened) / span_years, 2)

        run_lengths, run = [], 0
        for d in dirs:
            if d == "down":
                run += 1
            elif run:
                run_lengths.append(run)
                run = 0
        if run:
            run_lengths.append(run)
        out["max_down_streak"] = max(run_lengths, default=0)
        out["deep_down_runs"] = sum(
            1 for r in run_lengths if r >= chained_deep_run_len)
        out["chained_dips"] = bool(
            out["max_down_streak"] >= chained_max_down_streak
            or out["deep_down_runs"] >= chained_deep_run_count)

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
        anchor_price = float(last["price"])

        # The next price level that would print a threshold event: after a
        # down leg (anchor at 100) the next event is an up leg at >= 110;
        # after an up leg (anchor at 110) the next event is a down leg at
        # <= 99. Not a recommendation — just the level to compare against
        # current_price.
        if last_dir == "down":
            out["action_side"] = SIGNAL_SELL
            out["action_price"] = round(anchor_price * (1 + threshold_pct / 100), 4)
        else:
            out["action_side"] = SIGNAL_BUY
            out["action_price"] = round(anchor_price * (1 - threshold_pct / 100), 4)

        # How far current_price sits from action_price, signed so it always
        # reads as "price must move this much to trigger": negative on a BUY
        # row (price needs to fall), positive on a SELL row (price needs to
        # rise). Sorting by this surfaces tickers closest to their next
        # threshold event.
        out["pct_to_action"] = round(
            (out["action_price"] - out["current_price"]) / out["current_price"] * 100, 2)

    window_start = as_of - timedelta(days=recent_window_days)
    in_window = ev[(ev["date"].dt.date > window_start) & (ev["date"].dt.date <= as_of)]
    out["recent_events"] = [
        {"date": d.strftime("%Y-%m-%d"), "direction": dirn}
        for d, dirn in zip(in_window["date"], in_window["direction"])
    ]
    return out
