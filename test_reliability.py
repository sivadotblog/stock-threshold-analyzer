"""
Deterministic unit tests for the oscillation reliability metric.

Uses synthetic price series (no network) so the math is verified in isolation:
a clean oscillator should score high; a pure trend should score ~0.
"""

import numpy as np
import pandas as pd

from reliability import compute_reliability, compute_bullish_oscillation


def _prices(close):
    dates = pd.date_range("2019-01-01", periods=len(close), freq="B")
    return pd.DataFrame({"date": dates, "close": np.asarray(close, dtype=float)})


def test_clean_oscillator_scores_high():
    # ~5y of business days, a clean +/-15% sine -> crosses +/-10% periodically.
    t = np.arange(1260)
    close = 100.0 * (1 + 0.15 * np.sin(2 * np.pi * t / 60))
    r = compute_reliability(_prices(close), threshold_pct=10.0)

    assert not r["gated"], r
    assert r["n_up"] > 5 and r["n_down"] > 5, r
    assert r["balance"] > 0.8, r          # symmetric up/down
    assert r["mean_revert"] > 0.8, r      # no linear trend
    assert r["drift_score"] > 0.8, r      # ends where it started
    assert r["reliability"] > 0.4, r
    print("clean oscillator:", r["reliability"], r)


def test_pure_uptrend_scores_low():
    close = np.linspace(100, 400, 1260)   # relentless one-way ramp
    r = compute_reliability(_prices(close), threshold_pct=10.0)

    # Only 'up' triggers -> gated for missing down legs, score 0.
    assert r["reliability"] < 0.2, r
    assert r["n_down"] == 0, r
    print("pure uptrend:", r["reliability"], r["gate_reason"])


def test_too_few_events_gated():
    close = np.full(300, 100.0)            # flat line, never triggers
    close[150:] = 101.0
    r = compute_reliability(_prices(close), threshold_pct=10.0)
    assert r["gated"], r
    assert r["reliability"] == 0.0, r
    print("flat line:", r["gate_reason"])


# ---------------------------------------------------------------------------
# Bullish-oscillation metric: rewards UP-trend + two-sided swings ("like ZETA").
# ---------------------------------------------------------------------------

_T = np.arange(1260)
_SINE = 0.15 * np.sin(2 * np.pi * _T / 60)   # +/-15% swing -> crosses +/-10%


def test_bullish_uptrend_with_swings_scores_high():
    # Oscillation riding an upward ramp: higher highs / higher lows -- the ZETA case.
    close = np.linspace(100, 300, 1260) * (1 + _SINE)
    r = compute_bullish_oscillation(_prices(close), threshold_pct=10.0)

    assert not r["gated"], r
    assert r["n_up"] > 5 and r["n_down"] > 5, r   # genuinely two-sided
    assert r["trend"] > 0.8, r                    # rewarded for trending up
    assert r["activity"] > 0.7, r                 # swings often
    assert r["bullish_score"] > 0.6, r
    print("bullish uptrend:", r["bullish_score"], r)


def test_bullish_downtrend_with_swings_scores_low():
    # Same swings, downward ramp: the AMPL/BRZE/DV case -- swings but bleeds down.
    close = np.linspace(300, 80, 1260) * (1 + _SINE)
    r = compute_bullish_oscillation(_prices(close), threshold_pct=10.0)

    assert not r["gated"], r          # it DOES swing both ways
    assert r["n_up"] > 5 and r["n_down"] > 5, r
    assert r["trend"] < 0.2, r        # penalized for trending down
    assert r["bullish_score"] < 0.2, r
    print("bullish downtrend:", r["bullish_score"], r)


def test_bullish_flat_oscillator_scores_middling():
    # Pure sine, no trend: a clean range-bound oscillator is now only MIDDLING --
    # it doesn't trend up, so it's not "like ZETA".
    flat = 100.0 * (1 + _SINE)
    up = np.linspace(100, 300, 1260) * (1 + _SINE)
    r_flat = compute_bullish_oscillation(_prices(flat), threshold_pct=10.0)
    r_up = compute_bullish_oscillation(_prices(up), threshold_pct=10.0)

    assert not r_flat["gated"], r_flat
    assert 0.35 < r_flat["trend"] < 0.65, r_flat            # ~neutral
    assert r_flat["bullish_score"] < r_up["bullish_score"], (r_flat, r_up)
    print("bullish flat:", r_flat["bullish_score"], "vs up:", r_up["bullish_score"])


def test_bullish_pure_uptrend_no_swings_gated():
    # Straight ramp, no pullbacks: not an oscillator at all -> gated to 0.
    close = np.linspace(100, 400, 1260)
    r = compute_bullish_oscillation(_prices(close), threshold_pct=10.0)
    assert r["gated"], r
    assert r["n_down"] == 0, r
    assert r["bullish_score"] == 0.0, r
    print("bullish pure uptrend:", r["gate_reason"])


def test_bullish_too_few_events_gated():
    close = np.full(300, 100.0)
    close[150:] = 101.0
    r = compute_bullish_oscillation(_prices(close), threshold_pct=10.0)
    assert r["gated"], r
    assert r["bullish_score"] == 0.0, r
    print("bullish flat line:", r["gate_reason"])


if __name__ == "__main__":
    test_clean_oscillator_scores_high()
    test_pure_uptrend_scores_low()
    test_too_few_events_gated()
    test_bullish_uptrend_with_swings_scores_high()
    test_bullish_downtrend_with_swings_scores_low()
    test_bullish_flat_oscillator_scores_middling()
    test_bullish_pure_uptrend_no_swings_gated()
    test_bullish_too_few_events_gated()
    print("\nAll reliability unit tests passed!")
