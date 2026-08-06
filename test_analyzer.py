"""
Unit tests for the oscillation analyzer: event detection on hand-crafted
paths, the summary (counts, rate, trend filter, streak, action price,
recent-events window), and leaderboard ordering.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from reliability import (SIGNAL_BUY, SIGNAL_SELL, compute_oscillation_summary,
                         find_threshold_events)
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


def reformed_spiker_prices():
    """DIG-shaped: an early 12-month tripling, then ~2.7 years of ordinary
    ±10% oscillation. The spike is real but stale — older than the recency
    window — so the ticker should screen on its recent record."""
    ramp = 100.0 * 1.01 ** np.arange(130)                 # ~3.6x in ~6 months
    calm_t = np.arange(700)
    calm = ramp[-1] * (1 + 0.10 * np.sin(2 * np.pi * calm_t / 40))
    return make_prices(np.concatenate([ramp, calm]))


def chained_dip_prices():
    """NET-shaped: five -10% legs in a row, then six +11% legs. Net-positive
    and non-parabolic, but the worst BUY chain ran ~-41% underwater from the
    first rung before recovering."""
    closes = [100.0]
    for _ in range(5):
        closes.append(closes[-1] * 0.899)
    for _ in range(6):
        closes.append(closes[-1] * 1.11)
    return make_prices(closes)


def recurrent_chain_prices(n_chains=2):
    """CRWD-shaped: ``n_chains`` separate 4-deep dip chains, each fully
    recovered by five +11% legs. Never 5-deep, but repeatedly ~-34%
    underwater from the first BUY."""
    closes = [100.0]
    for _ in range(n_chains):
        for _ in range(4):
            closes.append(closes[-1] * 0.899)
        for _ in range(5):
            closes.append(closes[-1] * 1.11)
    return make_prices(closes)


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
    assert s["action_side"] == SIGNAL_BUY       # last leg was up -> next is a BUY trigger
    # recovery_rate is a transition probability over the whole window, not a
    # per-dip verdict — the guard is against failure/bounce classifications.
    assert not any("fail" in k or "bounce" in k for k in s)


# ---------------------------------------------------------------------------
# summary: counts, rate, trend, streak, action price
# ---------------------------------------------------------------------------

def test_mixed_summary():
    prices = make_prices(MIXED_CLOSES)
    s = compute_oscillation_summary(prices, threshold_pct=10.0)
    assert s["n_up"] == 2 and s["n_down"] == 3 and s["n_events"] == 5
    assert s["current_streak"] == 1             # last event was a single up-leg
    assert s["current_price"] == 84.0           # last close
    assert s["last_event_date"] == prices["date"].iloc[6].strftime("%Y-%m-%d")
    assert s["trend_positive"] is False         # 84 vs 100 start
    assert s["net_return_pct"] == pytest.approx(-16.0, abs=0.01)
    # last leg was up (SELL @ 86) -> next dip trigger is BUY <= 86 * 0.9
    assert s["action_side"] == SIGNAL_BUY
    assert s["action_price"] == pytest.approx(86 * 0.9, abs=0.01)


def test_action_price_after_down_leg():
    s = compute_oscillation_summary(make_prices([100, 89, 88]), threshold_pct=10.0)
    assert s["current_streak"] == -1
    assert s["current_price"] == 88.0
    # last leg was down (BUY @ 89) -> harvest trigger is SELL >= 89 * 1.1
    assert s["action_side"] == SIGNAL_SELL
    assert s["action_price"] == pytest.approx(89 * 1.1, abs=0.01)


def test_pct_to_action_sign_convention():
    # BUY row: current_price (84) sits above action_price (77.4) -> negative,
    # price must fall to trigger.
    buy = compute_oscillation_summary(make_prices(MIXED_CLOSES), threshold_pct=10.0)
    assert buy["pct_to_action"] == pytest.approx(
        (77.4 - 84) / 84 * 100, abs=0.01)
    assert buy["pct_to_action"] < 0

    # SELL row: current_price (88) sits below action_price (97.9) -> positive,
    # price must rise to trigger.
    sell = compute_oscillation_summary(make_prices([100, 89, 88]), threshold_pct=10.0)
    assert sell["pct_to_action"] == pytest.approx(
        (97.9 - 88) / 88 * 100, abs=0.01)
    assert sell["pct_to_action"] > 0


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


def test_no_events_no_action():
    s = compute_oscillation_summary(make_prices([100, 104, 97, 102] * 5),
                                    threshold_pct=10.0)
    assert s["n_events"] == 0
    assert s["action_side"] is None
    assert s["pct_to_action"] is None
    assert s["current_price"] == 102.0          # still reported with zero events
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
    assert s["action_side"] == SIGNAL_SELL      # last (only) legs are down -> harvest trigger


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


def test_old_spike_released_by_recency():
    s = compute_oscillation_summary(reformed_spiker_prices(), threshold_pct=10.0)
    assert s["max_run_up_pct"] > 200            # the spike is on the record...
    assert s["recent_run_up_pct"] < 200         # ...but not in the last 2 years
    assert s["parabolic"] is False


def test_recent_spike_still_flagged():
    s = compute_oscillation_summary(parabolic_prices(), threshold_pct=10.0)
    assert s["recent_run_up_pct"] >= 200        # ramp ends the series
    assert s["parabolic"] is True


def test_recency_window_is_configurable():
    s = compute_oscillation_summary(reformed_spiker_prices(), threshold_pct=10.0,
                                    parabolic_recency_days=10_000)
    assert s["parabolic"] is True               # whole history counts again


def test_sine_oscillator_run_up_stays_small():
    s = compute_oscillation_summary(sine_prices(), threshold_pct=10.0)
    # 90..110 range: worst run-up from a trailing low is ~22%
    assert s["max_run_up_pct"] < 30
    assert s["parabolic"] is False


# ---------------------------------------------------------------------------
# transitions: net resolved dips (the ranking key) + thin-history gate
# ---------------------------------------------------------------------------

def test_transition_counts_and_net_rate():
    # MIXED dirs: d,u,d,d,u -> transitions d>u, u>d, d>d, d>u
    s = compute_oscillation_summary(make_prices(MIXED_CLOSES), threshold_pct=10.0)
    assert s["dips_resolved"] == 2 and s["dips_deepened"] == 1
    assert s["recovery_rate"] == pytest.approx(2 / 3, abs=0.001)
    assert s["net_dips_per_year"] > 0
    assert s["thin_history"] is True            # only 5 completed legs


def _cycle_prices(n_round_trips, extra_up_legs, pad_to):
    """n_round_trips (down leg, up leg) pairs, then extra_up_legs pure up
    legs, then flat padding so both fixtures share the same span."""
    closes = [100.0]
    for _ in range(n_round_trips):
        closes.append(closes[-1] * 0.899)
        closes.append(closes[-1] * 1.11)
    for _ in range(extra_up_legs):
        closes.append(closes[-1] * 1.11)
    closes += [closes[-1]] * max(0, pad_to - len(closes))
    return make_prices(closes)


def test_net_legs_rewards_frequency_over_ratio_when_surplus_is_larger():
    """VICI-shaped (1 down, 4 up; ratio 4.0, surplus 3) vs SPXL-shaped
    (10 down, 14 up; ratio 1.4, surplus 4) over the same span: the higher
    absolute surplus wins despite the worse per-event ratio."""
    hi_ratio_lo_freq = _cycle_prices(1, 3, pad_to=300)   # ratio 4.0, surplus 3
    lo_ratio_hi_freq = _cycle_prices(10, 4, pad_to=300)  # ratio 1.4, surplus 4
    s_lo = compute_oscillation_summary(hi_ratio_lo_freq, threshold_pct=10.0)
    s_hi = compute_oscillation_summary(lo_ratio_hi_freq, threshold_pct=10.0)
    assert s_lo["n_up"] / s_lo["n_down"] > s_hi["n_up"] / s_hi["n_down"]
    assert s_hi["net_legs_per_year"] > s_lo["net_legs_per_year"]


def test_net_legs_per_year_is_up_minus_down_over_span():
    s = compute_oscillation_summary(sine_prices(), threshold_pct=10.0)
    assert s["net_legs_per_year"] == pytest.approx(
        (s["n_up"] - s["n_down"]) / s["span_years"], abs=0.01)


def test_sine_resolves_every_dip():
    s = compute_oscillation_summary(sine_prices(), threshold_pct=10.0)
    assert s["recovery_rate"] == 1.0            # strict down/up alternation
    assert s["dips_deepened"] == 0
    assert s["thin_history"] is False
    assert s["net_dips_per_year"] == pytest.approx(
        s["dips_resolved"] / s["span_years"], abs=0.05)


def test_no_dips_means_no_recovery_evidence():
    s = compute_oscillation_summary(make_prices([100, 111, 124]), threshold_pct=10.0)
    assert s["n_down"] == 0
    assert s["recovery_rate"] is None           # no dips = no evidence, not 1.0
    assert s["net_dips_per_year"] == 0.0


def test_min_events_is_configurable():
    s = compute_oscillation_summary(make_prices(MIXED_CLOSES), threshold_pct=10.0,
                                    min_events=5)
    assert s["thin_history"] is False


# ---------------------------------------------------------------------------
# short-history gate: a rate needs a denominator it actually earned, not just
# enough legs — a newly-listed leveraged ETF can clear min_events on
# volatility-inflated chop packed into a few months
# ---------------------------------------------------------------------------

def test_short_history_off_by_default():
    s = compute_oscillation_summary(sine_prices(), threshold_pct=10.0)
    assert s["short_history"] is False           # min_history_years=None -> gate off


def test_short_history_flagged_when_span_below_threshold():
    s = compute_oscillation_summary(sine_prices(), threshold_pct=10.0,
                                    min_history_years=5.0)
    assert s["span_years"] == pytest.approx(2.95, abs=0.01)
    assert s["short_history"] is True            # ~3y of data, needs 5y


def test_short_history_not_flagged_when_span_covers_threshold():
    s = compute_oscillation_summary(sine_prices(), threshold_pct=10.0,
                                    min_history_years=2.0)
    assert s["short_history"] is False           # ~3y of data clears 2y


# ---------------------------------------------------------------------------
# chained-dips gate
# ---------------------------------------------------------------------------

def test_chained_dips_flagged():
    s = compute_oscillation_summary(chained_dip_prices(), threshold_pct=10.0)
    assert s["max_down_streak"] == 5
    assert s["chained_dips"] is True
    assert s["trend_positive"] is True          # flagged, not a downtrender
    assert s["parabolic"] is False


def test_short_chains_not_flagged():
    s = compute_oscillation_summary(make_prices(MIXED_CLOSES), threshold_pct=10.0)
    assert s["max_down_streak"] == 2            # d4/d5 back-to-back downs
    assert s["chained_dips"] is False


def test_recurrent_deep_chains_flagged():
    s = compute_oscillation_summary(recurrent_chain_prices(2), threshold_pct=10.0)
    assert s["max_down_streak"] == 4            # never hits the depth cap...
    assert s["deep_down_runs"] == 2
    assert s["chained_dips"] is True            # ...but recurrence flags it


def test_single_deep_chain_stays_clean():
    """SPXL-shaped: one 4-deep chain in five years is an episode, not a
    pattern — below both the depth and the recurrence caps."""
    s = compute_oscillation_summary(recurrent_chain_prices(1), threshold_pct=10.0)
    assert s["max_down_streak"] == 4 and s["deep_down_runs"] == 1
    assert s["chained_dips"] is False


def test_chained_threshold_is_configurable():
    prices = make_prices([100, 89.9, 80.8, 72.6, 87.5, 105])   # 3-deep chain
    s = compute_oscillation_summary(prices, threshold_pct=10.0)
    assert s["max_down_streak"] == 3 and s["chained_dips"] is False
    strict = compute_oscillation_summary(prices, threshold_pct=10.0,
                                         chained_max_down_streak=3)
    assert strict["chained_dips"] is True       # same data, stricter cap


# ---------------------------------------------------------------------------
# leaderboard ordering
# ---------------------------------------------------------------------------

def test_leaderboard_positives_rank_above_downtrenders():
    prices = {
        "OSC": sine_prices(),                   # positive trend, many legs
        "DEC": declining_prices(),              # downtrend, zero up-legs
        "CLU": make_prices([100, 89.9, 80.8, 72.6, 87.5, 105]),  # positive, 5 legs
    }
    as_of = max(p["date"].iloc[-1] for p in prices.values())
    rows = compute_leaderboard_rows(prices, {"OSC": "Oscillator Corp"}, as_of, 10.0, 30)

    tickers = [r["ticker"] for r in rows]
    assert tickers[-1] == "DEC"                 # downtrender always last
    assert all(r["trend_positive"] for r in rows[:-1])
    # CLU's 5 events make it thin history: below the proven oscillator no
    # matter what its tiny-span rates say
    assert tickers[:2] == ["OSC", "CLU"]
    assert rows[0]["name"] == "Oscillator Corp"
    assert rows[1]["name"] == "CLU"             # unmapped ticker -> falls back to symbol

    payload = build_leaderboard(rows, 10.0, 5, universe_size=3,
                                generated_at="2026-07-14T00:00:00")
    assert payload["metric"] == "net_legs_per_year"
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


def test_leaderboard_chained_ranks_below_steady_above_parabolic():
    prices = {
        "CHN": chained_dip_prices(),            # steady but chain-dipper
        "OSC": sine_prices(),                   # steady, clean chains
        "PARA": parabolic_prices(),             # regime shift — least trustworthy
        "DEC": declining_prices(),              # downtrender
    }
    as_of = max(p["date"].iloc[-1] for p in prices.values())
    rows = compute_leaderboard_rows(prices, {}, as_of, 10.0, 30)
    # CHN's tiny span gives a huge up-legs/yr, yet the flag demotes it below
    # the clean oscillator — while still ranking above parabolic runners.
    assert [r["ticker"] for r in rows] == ["OSC", "CHN", "PARA", "DEC"]
    by_ticker = {r["ticker"]: r for r in rows}
    assert by_ticker["CHN"]["chained_dips"] is True
    assert by_ticker["OSC"]["chained_dips"] is False


def test_leaderboard_thin_ranks_below_steady_above_chained():
    prices = {
        "OSC": sine_prices(),                                    # proven oscillator
        "THN": make_prices([100, 89.9, 80.8, 72.6, 87.5, 105]),  # 5 events: thin
        "CHN": chained_dip_prices(),                             # 11 events, chained
    }
    as_of = max(p["date"].iloc[-1] for p in prices.values())
    rows = compute_leaderboard_rows(prices, {}, as_of, 10.0, 30)
    assert [r["ticker"] for r in rows] == ["OSC", "THN", "CHN"]
    by_ticker = {r["ticker"]: r for r in rows}
    assert by_ticker["THN"]["thin_history"] is True
    assert by_ticker["THN"]["chained_dips"] is False
    assert by_ticker["CHN"]["thin_history"] is False


def test_leaderboard_drops_zero_event_tickers():
    prices = {"FLAT": make_prices([100, 101, 99, 100] * 20)}
    rows = compute_leaderboard_rows(prices, {}, prices["FLAT"]["date"].iloc[-1],
                                    10.0, 30)
    assert rows == []


def test_leaderboard_short_history_ranks_at_thin_tier():
    """LMTL/AVGU-shaped: enough legs (13) to clear min_events, but crammed
    into ~18 days instead of years — the gate leg-count-only thin_history
    misses, because the ticker never lived through the lookback window."""
    prices = {
        "OSC": sine_prices(),                     # ~3y span, clean
        "YOUNG": _cycle_prices(5, 3, pad_to=14),   # 13 legs, ~18 days
    }
    as_of = max(p["date"].iloc[-1] for p in prices.values())
    rows = compute_leaderboard_rows(prices, {}, as_of, 10.0, 30,
                                    min_history_years=2.0)
    by_ticker = {r["ticker"]: r for r in rows}
    assert by_ticker["YOUNG"]["trend_positive"] is True
    assert by_ticker["YOUNG"]["thin_history"] is False    # 13 legs clears min_events
    assert by_ticker["YOUNG"]["short_history"] is True    # but only ~18 days of data
    assert [r["ticker"] for r in rows] == ["OSC", "YOUNG"]


def test_screen_filename_matches_threshold():
    from main import _screen_filename
    assert _screen_filename(5.0) == "bullish_screen_5pct.json"
    assert _screen_filename(10.0) == "bullish_screen_10pct.json"
    assert _screen_filename(12.5) == "bullish_screen_12.5pct.json"


def test_leaderboard_payloads_one_per_threshold():
    from main import _leaderboard_payloads

    prices = {
        "OSC": sine_prices(),
        "DEC": declining_prices(),
    }
    as_of = max(p["date"].iloc[-1] for p in prices.values())
    a = {
        "recent_window_days": 30,
        "parabolic_window_days": 365,
        "parabolic_max_run_up_pct": 200.0,
        "parabolic_recency_days": 730,
        "chained_max_down_streak": 5,
        "chained_deep_run_len": 4,
        "chained_deep_run_count": 2,
        "min_events": 10,
        "min_history_fraction": 0.9,
    }
    payloads = _leaderboard_payloads(
        prices, {"OSC": "test"}, as_of, [5.0, 10.0], years=5, a=a,
        universe_size=2, generated_at="2026-08-04T00:00:00")

    assert set(payloads) == {5.0, 10.0}
    assert payloads[5.0]["threshold_pct"] == 5.0
    assert payloads[10.0]["threshold_pct"] == 10.0
    assert payloads[5.0]["universe_size"] == 2
    # A tighter threshold never prints fewer events than a looser one for
    # the same sine wave.
    osc_5 = next(r for r in payloads[5.0]["results"] if r["ticker"] == "OSC")
    osc_10 = next(r for r in payloads[10.0]["results"] if r["ticker"] == "OSC")
    assert (osc_5["n_up"] + osc_5["n_down"]) >= (osc_10["n_up"] + osc_10["n_down"])


def test_leaderboard_payloads_flags_short_history():
    """main.py multiplies years * min_history_fraction and threads the
    product through to the short_history gate."""
    from main import _leaderboard_payloads

    prices = {
        "OSC": sine_prices(),                     # ~2.95y span
        "YOUNG": _cycle_prices(5, 3, pad_to=14),   # ~0.05y span
    }
    as_of = max(p["date"].iloc[-1] for p in prices.values())
    a = {
        "recent_window_days": 30,
        "parabolic_window_days": 365,
        "parabolic_max_run_up_pct": 200.0,
        "parabolic_recency_days": 730,
        "chained_max_down_streak": 5,
        "chained_deep_run_len": 4,
        "chained_deep_run_count": 2,
        "min_events": 10,
        "min_history_fraction": 0.9,
    }
    # years=3 -> min_history_years = 2.7: OSC's 2.95y clears it, YOUNG's
    # 0.05y doesn't.
    payloads = _leaderboard_payloads(
        prices, {}, as_of, [10.0], years=3, a=a,
        universe_size=2, generated_at="2026-08-05T00:00:00")
    by_ticker = {r["ticker"]: r for r in payloads[10.0]["results"]}
    assert by_ticker["OSC"]["short_history"] is False
    assert by_ticker["YOUNG"]["short_history"] is True
