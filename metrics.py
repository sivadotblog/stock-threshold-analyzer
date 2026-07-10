"""
Per-ticker predictive metrics over the down-event outcome stream (spec §2).

Primary ranking key is ``bounce_rate_wilson_low`` — the lower bound of the 95%
Wilson score interval on the bounce rate. It penalizes small samples smoothly,
replacing v1's hard >=6-event eligibility gate (kept only as the soft
``low_sample`` display flag).

Look-ahead guard (spec §6): every function here takes an explicit ``as_of`` and
filters ``date <= as_of`` *internally* — callers are never trusted to
pre-filter. Down events whose resolution falls after ``as_of`` are re-censored:
their outcome, days-to-resolution, MAE and return are treated as unknown.

Pure functions on DataFrames; no I/O, no network.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from events import OUTCOME_BOUNCE, OUTCOME_CONTINUATION, build_events

# 95% two-sided normal quantile for the Wilson score interval.
WILSON_Z_95 = 1.959963984540054

# Approximate trailing-window length in calendar days per year.
DAYS_PER_YEAR = 365.25


def wilson_lower_bound(successes: int, n: int, z: float = WILSON_Z_95) -> float:
    """Lower bound of the Wilson score interval for a binomial proportion.

    Returns 0.0 when ``n == 0`` (no evidence -> no credit).
    """
    if n <= 0:
        return 0.0
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = p + z2 / (2.0 * n)
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)
    return max(0.0, (center - margin) / denom)


def _empty_metrics(threshold_pct: float) -> dict:
    return {
        "threshold_pct": threshold_pct,
        "n_down_events": 0,
        "n_bounces": 0,
        "n_continuations": 0,
        "n_censored": 0,
        "bounce_rate": None,
        "bounce_rate_wilson_low": 0.0,
        "median_days_to_bounce": None,
        "p90_days_to_bounce": None,
        "median_mae_pct": None,
        "worst_mae_pct": None,
        "expectancy_per_trade_pct": None,
        "low_sample": True,
    }


def compute_bounce_metrics(events: pd.DataFrame,
                           as_of: date | str | pd.Timestamp,
                           threshold_pct: float,
                           window_years: float = 5.0,
                           low_sample_min_events: int = 10) -> dict:
    """Aggregate down-event outcomes into the §2 metric set, as of ``as_of``.

    ``events`` is the full ``events.build_events`` frame for one ticker. Only
    events with ``date`` in ``(as_of - window, as_of]`` are used, and an event
    whose resolution lies after ``as_of`` is treated as censored *as of that
    date* — this is the structural no-look-ahead guarantee.

    Notes on definitions:
    * ``bounce_rate`` = bounces / (bounces + continuations); censored events are
      excluded from the denominator but reported via ``n_censored``.
    * ``expectancy_per_trade_pct`` = mean signed ``resolution_return_pct`` over
      resolved events (bounces contribute ~+N%, continuations ~-N%), before
      costs — costs live in the backtest.
    * MAE aggregates cover only events resolved by ``as_of``: a censored
      event's stored MAE was measured to the end of the data window and would
      leak the future.
    """
    as_of = pd.Timestamp(as_of)
    out = _empty_metrics(threshold_pct)

    if events is None or events.empty:
        return out

    window_start = as_of - pd.Timedelta(days=window_years * DAYS_PER_YEAR)
    ev = events[(events["direction"] == "down")
                & (events["date"] > window_start)
                & (events["date"] <= as_of)].copy()
    if ev.empty:
        return out

    # Re-censor anything not resolved by as_of.
    unresolved = ev["resolution_date"].isna() | (ev["resolution_date"] > as_of)
    resolved = ev[~unresolved]

    n_down = int(len(ev))
    n_bounce = int((resolved["resolved"] == OUTCOME_BOUNCE).sum())
    n_cont = int((resolved["resolved"] == OUTCOME_CONTINUATION).sum())
    n_censored = int(unresolved.sum())
    n_resolved = n_bounce + n_cont

    out.update(
        n_down_events=n_down,
        n_bounces=n_bounce,
        n_continuations=n_cont,
        n_censored=n_censored,
        low_sample=n_down < low_sample_min_events,
        bounce_rate_wilson_low=round(wilson_lower_bound(n_bounce, n_resolved), 4),
    )

    if n_resolved > 0:
        out["bounce_rate"] = round(n_bounce / n_resolved, 4)
        out["expectancy_per_trade_pct"] = round(
            float(resolved["resolution_return_pct"].mean()), 4)
        mae = resolved["drawdown_beyond_trigger_pct"].astype(float)
        out["median_mae_pct"] = round(float(mae.median()), 4)
        out["worst_mae_pct"] = round(float(mae.max()), 4)

    bounces = resolved[resolved["resolved"] == OUTCOME_BOUNCE]
    if len(bounces) > 0:
        dtb = bounces["days_to_resolution"].astype(float)
        out["median_days_to_bounce"] = round(float(dtb.median()), 1)
        out["p90_days_to_bounce"] = round(float(dtb.quantile(0.9)), 1)

    return out


def compute_ticker_metrics(prices: pd.DataFrame,
                           threshold_pct: float,
                           as_of: date | str | pd.Timestamp,
                           window_years: float = 5.0,
                           low_sample_min_events: int = 10,
                           include_v1: bool = True) -> dict:
    """Convenience wrapper: prices -> events -> §2 metrics (+ deprecated v1 score).

    Enforces the as-of guard on the price series too (rows after ``as_of`` are
    dropped before event detection), then delegates to ``compute_bounce_metrics``.
    ``bullish_score_v1`` is computed alongside for the deprecation period and
    must be presented as deprecated wherever it is shown.
    """
    as_of = pd.Timestamp(as_of)
    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"], format="mixed", dayfirst=False)
    prices = prices[prices["date"] <= as_of].reset_index(drop=True)

    if len(prices) < 2:
        out = _empty_metrics(threshold_pct)
        out["bullish_score_v1"] = None
        return out

    events = build_events(prices, threshold_pct)
    out = compute_bounce_metrics(events, as_of, threshold_pct,
                                 window_years=window_years,
                                 low_sample_min_events=low_sample_min_events)

    if include_v1:
        # Deprecated v1 composite, kept for side-by-side comparison only.
        from reliability import compute_bullish_oscillation
        window_start = as_of - pd.Timedelta(days=window_years * DAYS_PER_YEAR)
        w = prices[prices["date"] > window_start].reset_index(drop=True)
        v1 = compute_bullish_oscillation(w, threshold_pct=threshold_pct,
                                         as_of=as_of.date())
        out["bullish_score_v1"] = None if v1["gated"] else v1["bullish_score"]
        out["v1_gate_reason"] = v1["gate_reason"] or None
    return out
