"""
Oscillation reliability scoring.

Scores how reliably a ticker "stably, periodically moves +/-N% up and down".
Pure functions only (no network) so the math is unit-testable in isolation.

The formulas, the chosen constants, and the rejected alternatives are documented
in reliability_metric.md. All tunables live here as named constants so they can
be calibrated in one place before scaling to a large universe.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

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

# ---------------------------------------------------------------------------
# Tunable constants (see reliability_metric.md). Calibrate here, nowhere else.
# ---------------------------------------------------------------------------
K_REG = 1.0          # CV -> score sharpness for regularity:  exp(-K_REG * CV_t)
K_AMP = 1.0          # CV -> score sharpness for amplitude:    exp(-K_AMP * CV_a)

# NOTE: `mean_revert` (1 - R^2 of a linear fit) was dropped from the scored axes
# during calibration: it rewards noise (a wildly volatile trender has low R^2 ->
# high mean_revert), propping up chaotic names that drift_score correctly
# penalizes. It is still computed below as a diagnostic. See reliability_metric.md.
WEIGHTS = {
    "regularity": 0.30,
    "drift_score": 0.30,
    "amplitude_consistency": 0.25,
    "balance": 0.15,
}

# Eligibility gate: too little signal to call a ticker "reliable" -> score 0.
GATE_MIN_EVENTS = 6
GATE_MIN_WINDOW_COVERAGE = 0.60

# --- bullish-oscillation tunables (see plan / reliability_metric.md §6) ---
# These drive `compute_bullish_oscillation`, which scores "oscillates LIKE ZETA":
# net-trends UP while swinging +/-N% both ways. Calibrate here, nowhere else.
ACTIVITY_HALF = 8.0   # both-sided swings at which `activity` = 0.5 (saturating)
K_TREND = 0.5         # logistic sharpness on signed trend-in-swing-units

_EPS = 1e-9


def _oscillation_gate(n_events: int, n_up: int, n_down: int,
                      coverage: float) -> tuple[bool, str]:
    """Shared eligibility gate for the oscillation metrics.

    Returns ``(ok, reason)``. ``ok`` is False (with a human reason) when there is
    too little signal to call a ticker an oscillator at all: too few events, only
    one direction, or events clustered in a sliver of the window.
    """
    if n_events < GATE_MIN_EVENTS:
        return False, f"only {n_events} events (need >= {GATE_MIN_EVENTS})"
    if n_up < 1 or n_down < 1:
        return False, "oscillation is one-directional (missing up or down legs)"
    if coverage < GATE_MIN_WINDOW_COVERAGE:
        return False, (
            f"events cover only {coverage:.0%} of the window "
            f"(need >= {GATE_MIN_WINDOW_COVERAGE:.0%})"
        )
    return True, ""


def _weighted_geometric_mean(scores: dict) -> float:
    """Weighted geometric mean of the sub-scores (see reliability_metric.md)."""
    total_w = sum(WEIGHTS.values())
    log_sum = sum(
        WEIGHTS[k] * math.log(max(scores[k], _EPS)) for k in WEIGHTS
    )
    return math.exp(log_sum / total_w)


def compute_reliability(prices: pd.DataFrame, threshold_pct: float = 10.0) -> dict:
    """
    Score one ticker's oscillation reliability in [0, 1] (1 = best).

    Parameters
    ----------
    prices : DataFrame with columns ['date', 'close'], ascending by date.
    threshold_pct : the +/-N% move that defines one oscillation leg.

    Returns a dict with the composite ``reliability``, every sub-score, the
    raw diagnostics, and ``gated`` / ``gate_reason`` when disqualified.
    """
    out = {
        "reliability": 0.0,
        "regularity": 0.0,
        "amplitude_consistency": 0.0,
        "drift_score": 0.0,
        "mean_revert": 0.0,
        "balance": 0.0,
        "n_up": 0,
        "n_down": 0,
        "n_events": 0,
        "window_coverage": 0.0,
        "mean_amplitude": 0.0,
        "mean_overshoot": 0.0,
        "alternation": 0.0,
        "net_return_pct": 0.0,
        "gated": True,
        "gate_reason": "",
    }

    if prices is None or len(prices) < 2:
        out["gate_reason"] = "insufficient price history"
        return out

    prices = prices.reset_index(drop=True)
    events = find_threshold_events(prices, threshold_pct)
    ev = events[events["direction"].isin(["up", "down"])].reset_index(drop=True)

    n_up = int((ev["direction"] == "up").sum())
    n_down = int((ev["direction"] == "down").sum())
    n_events = n_up + n_down
    out.update(n_up=n_up, n_down=n_down, n_events=n_events)

    # --- net drift diagnostic (computable even when gated) ---
    close = prices["close"].to_numpy(dtype=float)
    net_return = float((close[-1] - close[0]) / close[0])
    out["net_return_pct"] = round(net_return * 100, 2)

    # --- window coverage: do events span the window, or cluster in one stretch? ---
    total_span = (prices["date"].iloc[-1] - prices["date"].iloc[0]).days
    ev_dates = pd.to_datetime(ev["date"]) if n_events >= 1 else None
    ev_span = (ev_dates.iloc[-1] - ev_dates.iloc[0]).days if n_events >= 2 else 0
    coverage = ev_span / total_span if total_span > 0 else 0.0
    out["window_coverage"] = round(coverage, 3)

    # --- eligibility gate ---
    ok, reason = _oscillation_gate(n_events, n_up, n_down, coverage)
    if not ok:
        out["gate_reason"] = reason
        return out

    # --- 1. regularity: evenness of inter-event spacing ---
    dt = ev_dates.diff().dropna().dt.days.astype(float)
    dt = dt[dt > 0]
    mean_dt = float(dt.mean())
    cv_t = float(dt.std(ddof=1)) / mean_dt if mean_dt > _EPS and len(dt) >= 2 else 999.0
    regularity = math.exp(-K_REG * cv_t)

    # --- 2. amplitude consistency: do swings land near +/-N%? ---
    a = ev["pct_from_anchor"].abs().to_numpy(dtype=float)
    mean_a = float(a.mean())
    cv_a = float(a.std(ddof=1)) / mean_a if mean_a > _EPS and len(a) >= 2 else 999.0
    amplitude_consistency = math.exp(-K_AMP * cv_a)
    out["mean_amplitude"] = round(mean_a, 2)
    out["mean_overshoot"] = round(mean_a - threshold_pct, 2)

    # --- 3a. net drift, normalized by swing size ---
    drift_ratio = abs(net_return) / (mean_a / 100.0) if mean_a > _EPS else 999.0
    drift_score = 1.0 / (1.0 + drift_ratio)

    # --- 3b. trend strength via R^2 of close vs time ---
    t = np.arange(len(close), dtype=float)
    if np.std(close) > _EPS:
        r = float(np.corrcoef(t, close)[0, 1])
        trend_strength = r * r
    else:
        trend_strength = 0.0
    mean_revert = 1.0 - trend_strength

    # --- 4. direction balance + alternation diagnostic ---
    balance = 1.0 - abs(n_up - n_down) / n_events
    dirs = ev["direction"].to_numpy()
    flips = int(np.sum(dirs[1:] != dirs[:-1]))
    out["alternation"] = round(flips / (len(dirs) - 1), 3) if len(dirs) > 1 else 0.0

    scores = {
        "regularity": regularity,
        "amplitude_consistency": amplitude_consistency,
        "drift_score": drift_score,
        "mean_revert": mean_revert,
        "balance": balance,
    }
    reliability = _weighted_geometric_mean(scores)

    out.update({k: round(v, 4) for k, v in scores.items()})
    out["reliability"] = round(reliability, 4)
    out["gated"] = False
    out["gate_reason"] = ""
    return out


def _cagr_and_max_drawdown(close: np.ndarray, span_days: int) -> tuple[float, float]:
    """Annualized return and worst peak-to-trough drawdown (both as fractions).

    ``max_drawdown`` is <= 0 (e.g. -0.42 = a 42% drawdown).
    """
    cagr = 0.0
    years = span_days / 365.25
    if years > _EPS and close[0] > _EPS:
        cagr = float((close[-1] / close[0]) ** (1.0 / years) - 1.0)
    running_max = np.maximum.accumulate(close)
    max_drawdown = float(((close - running_max) / running_max).min())
    return cagr, max_drawdown


def compute_bullish_oscillation(prices: pd.DataFrame,
                                threshold_pct: float = 10.0) -> dict:
    """
    Score how much a ticker oscillates *like ZETA*: a BULLISH oscillator that
    net-trends **up** while swinging +/-N% up and down repeatedly.

    Unlike ``compute_reliability`` (which rewards flat / range-bound names and
    penalizes any trend), this rewards an upward trend and penalizes a downward
    one. The composite is a lean product of two axes, each in [0, 1]:

      * ``activity`` -- frequent *two-sided* +/-N% swings (one-directional => 0)
      * ``trend``    -- SIGNED net drift, normalized by swing size, through a
                        logistic: up -> 1, flat -> 0.5, down -> 0.

    ``bullish_score = activity * trend`` (either axis can veto). ZETA, the
    archetype, scores near the top; crashers that swing but bleed down score low;
    flat oscillators land in the middle.

    Returns the composite plus every axis and the diagnostics (regularity,
    amplitude_consistency, balance, cagr, max_drawdown, ...). ``gated`` / number
    fields mirror ``compute_reliability`` so the two are interchangeable in a
    screening table.
    """
    out = {
        "bullish_score": 0.0,
        "activity": 0.0,
        "trend": 0.0,
        # diagnostics (computed, not scored)
        "regularity": 0.0,
        "amplitude_consistency": 0.0,
        "balance": 0.0,
        "n_up": 0,
        "n_down": 0,
        "n_events": 0,
        "current_streak": 0,
        "last_event_date": None,
        "window_coverage": 0.0,
        "mean_amplitude": 0.0,
        "net_return_pct": 0.0,
        "cagr_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "gated": True,
        "gate_reason": "",
    }

    if prices is None or len(prices) < 2:
        out["gate_reason"] = "insufficient price history"
        return out

    prices = prices.reset_index(drop=True)
    prices["date"] = pd.to_datetime(prices["date"], format="mixed", dayfirst=False)
    events = find_threshold_events(prices, threshold_pct)
    ev = events[events["direction"].isin(["up", "down"])].reset_index(drop=True)

    n_up = int((ev["direction"] == "up").sum())
    n_down = int((ev["direction"] == "down").sum())
    n_events = n_up + n_down
    out.update(n_up=n_up, n_down=n_down, n_events=n_events)

    if n_events >= 1:
        dirs = ev["direction"].tolist()
        last_dir = dirs[-1]
        streak = 0
        for d in reversed(dirs):
            if d == last_dir:
                streak += 1
            else:
                break
        out["current_streak"] = streak if last_dir == "up" else -streak
        last_date = ev["date"].iloc[-1]
        out["last_event_date"] = (
            last_date.strftime("%Y-%m-%d")
            if hasattr(last_date, "strftime")
            else str(last_date)[:10]
        )

    close = prices["close"].to_numpy(dtype=float)
    net_return = float((close[-1] - close[0]) / close[0])
    out["net_return_pct"] = round(net_return * 100, 2)

    span_days = (prices["date"].iloc[-1] - prices["date"].iloc[0]).days
    cagr, max_dd = _cagr_and_max_drawdown(close, span_days)
    out["cagr_pct"] = round(cagr * 100, 2)
    out["max_drawdown_pct"] = round(max_dd * 100, 2)

    ev_dates = pd.to_datetime(ev["date"]) if n_events >= 1 else None
    ev_span = (ev_dates.iloc[-1] - ev_dates.iloc[0]).days if n_events >= 2 else 0
    coverage = ev_span / span_days if span_days > 0 else 0.0
    out["window_coverage"] = round(coverage, 3)

    # --- eligibility gate (shared with compute_reliability) ---
    ok, reason = _oscillation_gate(n_events, n_up, n_down, coverage)
    if not ok:
        out["gate_reason"] = reason
        return out

    # --- amplitude (also the denominator that normalizes the trend) ---
    a = ev["pct_from_anchor"].abs().to_numpy(dtype=float)
    mean_a = float(a.mean())
    out["mean_amplitude"] = round(mean_a, 2)

    # --- axis 1: oscillation activity (both-sided, saturating) ---
    swings = min(n_up, n_down)
    activity = swings / (swings + ACTIVITY_HALF)

    # --- axis 2: signed trend, in units of one swing, through a logistic ---
    trend_units = net_return / (mean_a / 100.0) if mean_a > _EPS else 0.0
    trend = 1.0 / (1.0 + math.exp(-K_TREND * trend_units))

    bullish_score = activity * trend

    # --- diagnostics (not scored): regularity, amplitude consistency, balance ---
    dt = ev_dates.diff().dropna().dt.days.astype(float)
    dt = dt[dt > 0]
    mean_dt = float(dt.mean()) if len(dt) >= 1 else 0.0
    cv_t = float(dt.std(ddof=1)) / mean_dt if mean_dt > _EPS and len(dt) >= 2 else 999.0
    out["regularity"] = round(math.exp(-cv_t), 4)
    cv_a = float(a.std(ddof=1)) / mean_a if mean_a > _EPS and len(a) >= 2 else 999.0
    out["amplitude_consistency"] = round(math.exp(-cv_a), 4)
    out["balance"] = round(1.0 - abs(n_up - n_down) / n_events, 4)

    out["activity"] = round(activity, 4)
    out["trend"] = round(trend, 4)
    out["bullish_score"] = round(bullish_score, 4)
    out["gated"] = False
    out["gate_reason"] = ""
    return out
