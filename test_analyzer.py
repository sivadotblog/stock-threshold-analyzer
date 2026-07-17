"""
Unit tests for the oscillation analyzer: event detection on hand-crafted
paths, the summary (counts, rate, trend filter, streak, stateless signal,
recent-events window), and leaderboard ordering.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from reliability import (SIGNAL_BUY, SIGNAL_NONE, SIGNAL_SELL,
                         compute_oscillation_summary, find_threshold_events)
from report import build_leaderboard, compute_leaderboard_rows

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def make_prices(closes, start="2020-01-02"):
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"date": dates, "close": [float(c) for c in closes]})


def sine_prices(n=771, period=40, mid=100.0, amp=10.0):
    """Oscillates 90..110: with N=10 every leg triggers. Ends on a peak."""
    t = np.arange(n)
    return make_prices(mid + amp * np.sin(2 * np.pi * t / period))


def declining_prices(n=400):
    """Monotonic -0.5%/day: down events only, net trend firmly negative."""
    return make_prices(100.0 * 0.995 ** np.arange(n))


def parabolic_prices():
    """CIFR-shaped: ~flat around 100 for a year, then ~5x in six months with
    wiggles big enough to print plenty of ±10% legs along the way."""
    t = np.arange(260)
    flat = 100.0 + 8.0 * np.sin(2 * np.pi * t / 40)
    ramp = flat[-1] * 1.013 ** np.arange(1, 131)          # ~5.3x in ~6 months
    wiggle = 1 + 0.12 * np.sin(2 * np.pi * np.arange(1, 131) / 20)
    return make_prices(np.concatenate([flat, ramp * wiggle]))


def steady_grower_prices():
    """TQQQ-shaped: ~+40%/yr drift with ±12% swings — strong but not
    parabolic; the worst 12-month run-up stays well under 200%."""
    t = np.arange(771)
    drift = 100.0 * 1.0014 ** t
    return make_prices(drift * (1 + 0.12 * np.sin(2 * np.pi * t / 40)))


# Hand-crafted mixed path with fully known events:
#   d0 100 start | d1 89 down | d2 85 | d3 100 up | d4 88 down | d5 77 down
#   d6 86 up | d7 84
MIXED_CLOSES = [100, 89, 85, 100, 88, 77, 86, 84]


# ---------------------------------------------------------------------------
# event detection
# ---------------------------------------------------------------------------

def test_mixed_event_sequence():
    prices = make_prices(MIXED_CLOSES)
    ev = find_threshold_events(prices, 10.0)
    assert ev["direction"].tolist() == [
        "start", "down", "up", "down", "down", "up"]
    assert ev["price"].tolist() == [100, 89, 100, 88, 77, 86]


def test_dip_cluster_counts_legs_not_failures():
    """-10% x3 then two +20% legs: three down-legs and two up-legs, full stop.
    Nothing in the output classifies the consecutive dips as failures."""
    prices = make_prices([100, 89.9, 80.8, 72.6, 87.5, 105])
    s = compute_oscillation_summary(prices, threshold_pct=10.0)
    assert s["n_down"] == 3 and s["n_up"] == 2
    assert s["trend_positive"] is True          # net +5%
    assert s["signal"] == SIGNAL_SELL           # last leg was up
    assert not any("fail" in k or "bounce" in k or "recover" in k for k in s)


# ---------------------------------------------------------------------------
# summary: counts, rate, trend, streak, signal
# ---------------------------------------------------------------------------

def test_mixed_summary():
    prices = make_prices(MIXED_CLOSES)
    s = compute_oscillation_summary(prices, threshold_pct=10.0)
    assert s["n_up"] == 2 and s["n_down"] == 3 and s["n_events"] == 5
    assert s["current_streak"] == 1             # last event was a single up-leg
    assert s["signal"] == SIGNAL_SELL
    assert s["signal_price"] == 86.0
    assert s["last_event_date"] == prices["date"].iloc[6].strftime("%Y-%m-%d")
    assert s["pct_since_signal"] == pytest.approx((84 - 86) / 86 * 100, abs=0.01)
    assert s["trend_positive"] is False         # 84 vs 100 start
    assert s["net_return_pct"] == pytest.approx(-16.0, abs=0.01)
    # last signal SELL @ 86 -> next dip trigger at 86 * 0.9
    assert s["target_side"] == SIGNAL_BUY
    assert s["target_price"] == pytest.approx(86 * 0.9, abs=0.01)
    # previous event was the d5 down leg at 77
    assert s["prev_signal"] == SIGNAL_BUY
    assert s["prev_signal_price"] == 77.0
    assert s["prev_signal_date"] == prices["date"].iloc[5].strftime("%Y-%m-%d")


def test_buy_signal_after_down_leg():
    s = compute_oscillation_summary(make_prices([100, 89, 88]), threshold_pct=10.0)
    assert s["signal"] == SIGNAL_BUY
    assert s["signal_price"] == 89.0
    assert s["current_streak"] == -1
    assert s["pct_since_signal"] == pytest.approx((88 - 89) / 89 * 100, abs=0.01)
    # BUY at 89 -> harvest target SELL >= 89 * 1.1
    assert s["target_side"] == SIGNAL_SELL
    assert s["target_price"] == pytest.approx(89 * 1.1, abs=0.01)
    assert s["prev_signal"] is None             # only one event so far


def test_nan_closes_are_dropped():
    """A half-formed Yahoo bar (NaN close) must not poison the stats or leak
    NaN into the payload (NaN is invalid JSON and broke the site)."""
    closes = MIXED_CLOSES + [float("nan")]
    s = compute_oscillation_summary(make_prices(closes), threshold_pct=10.0)
    clean = compute_oscillation_summary(make_prices(MIXED_CLOSES), threshold_pct=10.0)
    assert s == clean

    from main import _sanitize
    assert _sanitize({"a": float("nan"), "b": [1.0, float("inf")], "c": 2.5}) == \
        {"a": None, "b": [1.0, None], "c": 2.5}


def test_no_events_no_signal():
    s = compute_oscillation_summary(make_prices([100, 104, 97, 102] * 5),
                                    threshold_pct=10.0)
    assert s["n_events"] == 0
    assert s["signal"] == SIGNAL_NONE
    assert s["up_legs_per_year"] == 0.0


def test_sine_rate_and_trend():
    s = compute_oscillation_summary(sine_prices(), threshold_pct=10.0)
    # one up-leg per 40-bday period (~56 calendar days) -> roughly 6.5/yr
    assert 4.0 < s["up_legs_per_year"] < 9.0
    assert s["n_up"] >= 10
    assert s["trend_positive"] is True          # starts at 100, ends on the 110 peak
    assert s["max_drawdown_pct"] == pytest.approx(-18.18, abs=0.1)  # 110 -> 90


def test_decliner_is_flagged_not_scored():
    s = compute_oscillation_summary(declining_prices(), threshold_pct=10.0)
    assert s["n_up"] == 0
    assert s["up_legs_per_year"] == 0.0
    assert s["trend_positive"] is False
    assert s["cagr_pct"] < 0
    assert s["signal"] == SIGNAL_BUY            # last (only) legs are down


def test_recent_events_window():
    prices = make_prices(MIXED_CLOSES)
    s = compute_oscillation_summary(prices, threshold_pct=10.0)
    # all events are within 30 days of the last price date
    assert [e["direction"] for e in s["recent_events"]] == [
        "down", "up", "down", "down", "up"]
    # a much older event falls out of the window
    far = compute_oscillation_summary(prices, threshold_pct=10.0,
                                      as_of=(prices["date"].iloc[-1]
                                             + pd.Timedelta(days=60)).date())
    assert far["recent_events"] == []


# ---------------------------------------------------------------------------
# parabolic gate
# ---------------------------------------------------------------------------

def test_parabolic_spike_is_flagged():
    s = compute_oscillation_summary(parabolic_prices(), threshold_pct=10.0)
    assert s["parabolic"] is True
    assert s["max_run_up_pct"] > 300            # ~5x from the flat-year lows
    assert s["trend_positive"] is True          # still net-up: flagged, not a downtrender
    assert s["n_up"] > 0                        # the spike printed legs — that's the problem


def test_steady_grower_not_flagged():
    s = compute_oscillation_summary(steady_grower_prices(), threshold_pct=10.0)
    assert s["parabolic"] is False
    assert 0 < s["max_run_up_pct"] < 200
    assert s["trend_positive"] is True


def test_parabolic_cap_is_configurable():
    prices = steady_grower_prices()
    strict = compute_oscillation_summary(prices, threshold_pct=10.0,
                                         parabolic_max_run_up_pct=50.0)
    assert strict["parabolic"] is True          # same data, stricter cap


def test_sine_oscillator_run_up_stays_small():
    s = compute_oscillation_summary(sine_prices(), threshold_pct=10.0)
    # 90..110 range: worst run-up from a trailing low is ~22%
    assert s["max_run_up_pct"] < 30
    assert s["parabolic"] is False


# ---------------------------------------------------------------------------
# leaderboard ordering
# ---------------------------------------------------------------------------

def test_leaderboard_positives_rank_above_downtrenders():
    prices = {
        "OSC": sine_prices(),                   # positive trend, many legs
        "DEC": declining_prices(),              # downtrend, zero up-legs
        "CLU": make_prices([100, 89.9, 80.8, 72.6, 87.5, 105]),  # positive, 2 legs, tiny span
    }
    as_of = max(p["date"].iloc[-1] for p in prices.values())
    rows = compute_leaderboard_rows(prices, {"OSC": "test"}, as_of, 10.0, 30)

    tickers = [r["ticker"] for r in rows]
    assert tickers[-1] == "DEC"                 # downtrender always last
    assert all(r["trend_positive"] for r in rows[:-1])
    # positives sorted by up-legs/yr desc (CLU's tiny span gives a huge rate)
    assert tickers[:2] == ["CLU", "OSC"]
    assert rows[0]["category"] == ""            # unmapped ticker -> empty category

    payload = build_leaderboard(rows, 10.0, 5, universe_size=3,
                                generated_at="2026-07-14T00:00:00")
    assert payload["metric"] == "up_legs_per_year"
    assert [r["rank"] for r in payload["results"]] == [1, 2, 3]


def test_leaderboard_parabolic_ranks_below_steady_above_downtrenders():
    prices = {
        "PARA": parabolic_prices(),             # trend-positive but parabolic
        "OSC": sine_prices(),                   # steady oscillator
        "DEC": declining_prices(),              # downtrender
    }
    as_of = max(p["date"].iloc[-1] for p in prices.values())
    rows = compute_leaderboard_rows(prices, {}, as_of, 10.0, 30)
    tickers = [r["ticker"] for r in rows]
    # PARA prints far more legs/yr than OSC, yet the flag demotes it
    assert tickers == ["OSC", "PARA", "DEC"]
    by_ticker = {r["ticker"]: r for r in rows}
    assert by_ticker["PARA"]["parabolic"] is True
    assert by_ticker["OSC"]["parabolic"] is False


def test_leaderboard_drops_zero_event_tickers():
    prices = {"FLAT": make_prices([100, 101, 99, 100] * 20)}
    rows = compute_leaderboard_rows(prices, {}, prices["FLAT"]["date"].iloc[-1],
                                    10.0, 30)
    assert rows == []
