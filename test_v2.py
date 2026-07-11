"""
v2 unit tests (spec §6): synthetic-price fixtures with known event sequences,
Wilson bound, censoring, MAE, the look-ahead guard, engine mechanics, and the
signal/backtest parity invariants.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import (BUY_SETUP, END_OF_PERIOD, SELL_RECOVERY, SELL_STOP,
                      SELL_TIME, rank_asof, run_engine)
from events import build_events, down_event_outcomes
from metrics import compute_bounce_metrics, compute_ticker_metrics, wilson_lower_bound
from signals import SUPPRESSED, evaluate_states
from validate import interpret, run_validation, spearman_rho

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def make_prices(closes, start="2020-01-02"):
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"date": dates, "close": [float(c) for c in closes]})


def make_ohlc(prices: pd.DataFrame, opens=None, lows=None):
    """OHLC bars consistent with a close series (open defaults to the prior
    close, low to min(open, close))."""
    closes = prices["close"].to_numpy(dtype=float)
    if opens is None:
        opens = np.concatenate([[closes[0]], closes[:-1]])
    opens = np.asarray(opens, dtype=float)
    if lows is None:
        lows = np.minimum(opens, closes)
    return pd.DataFrame({
        "date": prices["date"], "open": opens,
        "high": np.maximum(opens, closes), "low": np.asarray(lows, dtype=float),
        "close": closes,
    })


def sine_prices(n=771, period=40, mid=100.0, amp=10.0):
    """Oscillates 90..110: with N=10 every descent fires exactly one down
    trigger that always resolves as a bounce. Ends on a peak (no censoring)."""
    t = np.arange(n)
    return make_prices(mid + amp * np.sin(2 * np.pi * t / period))


def declining_prices(n=400):
    """Monotonic -0.5%/day: every down event resolves as a continuation,
    except the final one, which stays censored."""
    return make_prices(100.0 * 0.995 ** np.arange(n))


# Hand-crafted mixed path with fully known outcomes:
#   d0 100 | d1 89 down | d2 85 | d3 100 up | d4 88 down | d5 77 down
#   d6 86 up | d7 84
MIXED_CLOSES = [100, 89, 85, 100, 88, 77, 86, 84]


# ---------------------------------------------------------------------------
# §1 events + outcome records
# ---------------------------------------------------------------------------

def test_mixed_outcome_records():
    prices = make_prices(MIXED_CLOSES)
    d = prices["date"]
    ev = down_event_outcomes(build_events(prices, 10.0))

    assert list(ev["resolved"]) == ["bounce", "continuation", "bounce"]
    assert list(ev["date"]) == [d[1], d[4], d[5]]
    assert list(ev["resolution_date"]) == [d[3], d[5], d[6]]
    assert ev["days_to_resolution"].tolist() == [
        (d[3] - d[1]).days, (d[5] - d[4]).days, (d[6] - d[5]).days]
    # MAE: worst close between trigger and resolution, relative to trigger
    assert ev["drawdown_beyond_trigger_pct"].tolist() == pytest.approx(
        [(89 - 85) / 89 * 100, (88 - 77) / 88 * 100, 0.0], abs=1e-3)
    assert ev["resolution_return_pct"].tolist() == pytest.approx(
        [(100 - 89) / 89 * 100, (77 - 88) / 88 * 100, (86 - 77) / 77 * 100],
        abs=1e-3)


def test_sine_all_bounces():
    prices = sine_prices()
    m = compute_bounce_metrics(build_events(prices, 10.0),
                               as_of=prices["date"].iloc[-1],
                               threshold_pct=10.0, window_years=10)
    assert m["n_down_events"] >= 10
    assert m["bounce_rate"] == 1.0
    assert m["n_censored"] == 0
    assert m["n_continuations"] == 0
    assert 0.5 < m["bounce_rate_wilson_low"] < 1.0  # penalized but high
    assert m["expectancy_per_trade_pct"] > 0


def test_decline_all_continuations_with_censoring():
    prices = declining_prices()
    m = compute_bounce_metrics(build_events(prices, 10.0),
                               as_of=prices["date"].iloc[-1],
                               threshold_pct=10.0, window_years=10)
    assert m["n_down_events"] >= 10
    assert m["bounce_rate"] == 0.0
    assert m["bounce_rate_wilson_low"] == 0.0
    assert m["n_bounces"] == 0
    assert m["n_censored"] == 1          # the unresolved final leg is KEPT
    assert m["median_days_to_bounce"] is None
    assert m["expectancy_per_trade_pct"] < 0


# ---------------------------------------------------------------------------
# §2 metrics: Wilson bound, aggregates
# ---------------------------------------------------------------------------

def test_wilson_reference_values():
    assert wilson_lower_bound(0, 0) == 0.0
    assert wilson_lower_bound(8, 10) == pytest.approx(0.4902, abs=1e-3)
    assert wilson_lower_bound(5, 5) == pytest.approx(0.5655, abs=1e-3)
    # more evidence at the same rate -> tighter bound
    assert wilson_lower_bound(80, 100) > wilson_lower_bound(8, 10)
    assert 0.0 <= wilson_lower_bound(1, 2) <= 1.0


def test_mixed_metrics_aggregates():
    prices = make_prices(MIXED_CLOSES)
    m = compute_ticker_metrics(prices, 10.0, as_of=prices["date"].iloc[-1],
                               window_years=5, include_v1=False)
    assert m["n_down_events"] == 3
    assert m["n_bounces"] == 2 and m["n_continuations"] == 1
    assert m["bounce_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert m["median_mae_pct"] == pytest.approx(4.4944, abs=1e-3)
    assert m["worst_mae_pct"] == pytest.approx(12.5, abs=1e-3)
    assert m["low_sample"] is True  # 3 < 10
    exp = ((100 - 89) / 89 + (77 - 88) / 88 + (86 - 77) / 77) / 3 * 100
    assert m["expectancy_per_trade_pct"] == pytest.approx(exp, abs=1e-3)


# ---------------------------------------------------------------------------
# §6 look-ahead guard
# ---------------------------------------------------------------------------

def test_lookahead_future_event_does_not_leak():
    """Plant a resolution AFTER as_of: it must count as censored, and metrics
    from the full series must equal metrics from a series truncated at as_of."""
    prices = make_prices(MIXED_CLOSES)
    d = prices["date"]
    as_of = d[4]  # the d4 down event's resolution (d5) is in the future

    m = compute_bounce_metrics(build_events(prices, 10.0), as_of=as_of,
                               threshold_pct=10.0, window_years=5)
    assert m["n_down_events"] == 2         # d1 and d4
    assert m["n_bounces"] == 1             # d1 resolved by d3
    assert m["n_censored"] == 1            # d4 unresolved as of d4
    assert m["n_continuations"] == 0
    # censored MAE (measured into the future) must NOT enter aggregates
    assert m["median_mae_pct"] == pytest.approx(4.4944, abs=1e-3)
    assert m["worst_mae_pct"] == pytest.approx(4.4944, abs=1e-3)

    full = compute_ticker_metrics(prices, 10.0, as_of=as_of, include_v1=False)
    truncated = compute_ticker_metrics(prices.iloc[:5], 10.0, as_of=as_of,
                                       include_v1=False)
    assert full == truncated


def test_metrics_window_excludes_old_events():
    prices = make_prices(MIXED_CLOSES)
    m = compute_bounce_metrics(build_events(prices, 10.0),
                               as_of=prices["date"].iloc[-1],
                               threshold_pct=10.0,
                               window_years=5 / 365.25)  # ~5 days back only
    # d7 (Mon) minus 5 days = d4's date: strict > keeps d5 only
    assert m["n_down_events"] == 1


# ---------------------------------------------------------------------------
# §3 validation harness
# ---------------------------------------------------------------------------

def test_spearman_rho():
    x = np.arange(20, dtype=float)
    assert spearman_rho(x, x) == pytest.approx(1.0)
    assert spearman_rho(x, -x) == pytest.approx(-1.0)


def test_interpret_verdicts():
    split = {"bounce_rate_rho": 0.5, "bounce_rate_p": 0.001, "n_tickers": 60}
    rolling = {"n_steps": 8, "median_rho": 0.35, "frac_positive": 0.9}
    assert interpret(split, rolling)["status"] == "PASSED"

    weak = interpret({**split, "bounce_rate_rho": 0.2}, rolling)
    assert weak["status"] == "WEAK"

    fail = interpret({**split, "bounce_rate_rho": 0.02, "bounce_rate_p": 0.6},
                     rolling)
    assert fail["status"] == "FAILED"
    assert any("regime" in ln.lower() for ln in fail["interpretation"])


def test_validation_detects_persistent_cross_section():
    """Half the tickers always bounce (sines), half never do (decliners):
    persistence across halves is perfect, the harness must PASS."""
    rng = np.random.default_rng(0)
    events = {}
    for i in range(10):
        n = int(rng.integers(1200, 1300))
        events[f"BNC{i}"] = build_events(
            sine_prices(n=n, period=int(rng.integers(35, 45))), 10.0)
        events[f"DEC{i}"] = build_events(declining_prices(n=n), 10.0)

    start = pd.Timestamp("2020-01-02")
    end = start + pd.Timedelta(days=5 * 365)
    cfg = {"min_events_per_half": 5, "permutations": 2000, "seed": 42,
           "rho_pass": 0.30, "p_pass": 0.05, "rho_weak": 0.15,
           "rolling_step_months": 3, "rolling_train_years": 2.5,
           "rolling_test_years": 1.0, "rolling_min_steps": 4}
    res = run_validation(events, start, end, 10.0, cfg)
    assert res["split_half"]["bounce_rate_rho"] > 0.5
    assert res["split_half"]["bounce_rate_p"] < 0.05
    assert res["status"] == "PASSED"


# ---------------------------------------------------------------------------
# §4 engine mechanics
# ---------------------------------------------------------------------------

ENGINE_CFG = {
    "threshold_pct": 10.0, "window_years": 5, "low_sample_min_events": 1,
    "top_k": 5, "max_positions": 5, "stop_mae_mult": 1.5, "max_hold_days": 30,
    "cost_bps_per_side": 0, "commission_per_trade": 0.0,
    "starting_cash": 10000.0, "min_events_asof": 1,
}

# History d0-d3 makes ticker A rankable (one resolved bounce, MAE 4.4944%);
# the backtest calendar starts at d4.
SCEN_A_CLOSES = [100, 89, 85, 100, 100, 89, 90, 98, 100, 100]


def scenario(closes, opens=None, lows=None, cal_start=4, cfg=None,
             tax_rate=0.0):
    prices = make_prices(closes)
    ohlc = make_ohlc(prices, opens=opens, lows=lows)
    events = {"A": build_events(prices, 10.0)}
    calendar = pd.DatetimeIndex(prices["date"].iloc[cal_start:])
    result = run_engine(events, {"A": ohlc}.get, calendar, cfg or ENGINE_CFG,
                        tax_rate=tax_rate)
    return prices, result


def test_engine_recovery_roundtrip():
    opens = [100, 100, 89, 85, 100, 100, 88, 90, 100, 100]
    prices, res = scenario(SCEN_A_CLOSES, opens=opens)
    d = prices["date"]

    trades = res["trades"]
    assert len(trades) == 1
    t = trades.iloc[0]
    assert t["trigger_date"] == d[5] and t["trigger_price"] == 89.0
    assert t["entry_date"] == d[6] and t["entry_price"] == 88.0  # next open
    assert t["exit_date"] == d[8] and t["exit_price"] == 100.0
    assert t["exit_reason"] == SELL_RECOVERY
    assert t["pnl_pct"] == pytest.approx((100 - 88) / 88 * 100, abs=1e-3)

    sig = res["signals"]
    assert ((sig["state"] == BUY_SETUP) & (sig["date"] == d[5])).any()
    assert ((sig["state"] == SELL_RECOVERY) & (sig["date"] == d[7])).any()

    # equity: 10000 + (10000/5 slots / 88) * 12
    final = res["equity_curve"]["equity"].iloc[-1]
    assert final == pytest.approx(10000 + (2000 / 88) * 12, abs=0.01)


def test_engine_costs_applied_per_side():
    opens = [100, 100, 89, 85, 100, 100, 88, 90, 100, 100]
    cfg = {**ENGINE_CFG, "cost_bps_per_side": 10}
    _, res = scenario(SCEN_A_CLOSES, opens=opens, cfg=cfg)
    t = res["trades"].iloc[0]
    entry_fill, exit_fill = 88 * 1.001, 100 * 0.999
    assert t["pnl_pct"] == pytest.approx(
        (exit_fill - entry_fill) / entry_fill * 100, abs=1e-3)


def test_engine_hard_stop_intraday():
    opens = [100, 100, 89, 85, 100, 100, 88, 87, 87, 87]
    lows = [100, 89, 85, 85, 100, 89, 82, 86, 86, 86]  # d6 low breaches stop
    closes = [100, 89, 85, 100, 100, 89, 87, 87, 87, 87]
    prices, res = scenario(closes, opens=opens, lows=lows)
    d = prices["date"]
    t = res["trades"].iloc[0]
    stop = 89 * (1 - 1.5 * 4.4944 / 100)
    assert t["exit_reason"] == SELL_STOP
    assert t["exit_date"] == d[6]  # same-day resting stop
    assert t["exit_price"] == pytest.approx(stop, abs=1e-2)
    sig = res["signals"]
    assert ((sig["state"] == SELL_STOP) & (sig["date"] == d[6])).any()


def test_engine_time_stop():
    # flat at 87 after entry: no recovery (needs 97.9), no stop breach
    closes = [100, 89, 85, 100, 100, 89] + [87] * 40
    prices, res = scenario(closes)
    t = res["trades"].iloc[0]
    assert t["exit_reason"] == SELL_TIME
    assert t["days_held"] >= 30
    assert ((res["signals"]["state"] == SELL_TIME)).any()


def test_engine_after_tax_run():
    opens = [100, 100, 89, 85, 100, 100, 88, 90, 100, 100]
    _, pre = scenario(SCEN_A_CLOSES, opens=opens)
    _, post = scenario(SCEN_A_CLOSES, opens=opens, tax_rate=0.35)
    gain = (2000 / 88) * 12
    assert post["taxes_paid"] == pytest.approx(0.35 * gain, abs=0.01)
    assert (post["equity_curve"]["equity"].iloc[-1]
            == pytest.approx(pre["equity_curve"]["equity"].iloc[-1]
                             - 0.35 * gain, abs=0.01))


def test_rank_asof_uses_only_past_data():
    """A ticker whose only resolved bounce happens AFTER as_of must not rank."""
    prices = make_prices(SCEN_A_CLOSES)
    events = {"A": build_events(prices, 10.0)}
    d = prices["date"]
    assert rank_asof(events, d[4], ENGINE_CFG)["ticker"].tolist() == ["A"]
    # before d3's up-trigger, the d1 down event is unresolved -> unrankable
    assert rank_asof(events, d[2], ENGINE_CFG).empty


# ---------------------------------------------------------------------------
# §5.5 signal states + §6 signal/backtest parity
# ---------------------------------------------------------------------------

def test_signal_states_buy_setup_not_gated_by_validation():
    """The universe-wide validation status is informational only (see
    signals.py docstring): pooling the whole universe into one cross-sectional
    test can mask a real, sector-specific signal, so it must not silently
    suppress every ticker's BUY_SETUP. Only the per-ticker low-sample gate
    (thin track record) suppresses."""
    # d9 close 88 prints a fresh down-trigger (anchor 98) on the last day
    closes = [100, 89, 85, 100, 100, 89, 90, 98, 100, 88]
    opens = [100, 100, 89, 85, 100, 100, 88, 90, 100, 100]
    prices, res = scenario(closes, opens=opens)
    as_of = prices["date"].iloc[-1]

    for status in ("PASSED", "WEAK", "FAILED", "NOT_RUN"):
        rows = evaluate_states(res, as_of, ENGINE_CFG, status)
        buy = next(r for r in rows if r["state"] == BUY_SETUP)
        assert buy["ticker"] == "A"
        assert buy["trigger_price"] == 88.0
        assert buy["actionable_from"] > str(as_of.date())  # never same-day
        assert buy["stop_price"] is not None
        assert "bounced" in buy["base_rate"]
        assert buy["validation_status"] == status  # attached, not enforced


def test_signal_states_low_sample_still_suppressed():
    """The per-ticker low-sample gate is unrelated to the universe-wide
    validation test and must still apply."""
    closes = [100, 89, 85, 100, 100, 89, 90, 98, 100, 88]
    opens = [100, 100, 89, 85, 100, 100, 88, 90, 100, 100]
    cfg = {**ENGINE_CFG, "low_sample_min_events": 10}
    prices, res = scenario(closes, opens=opens, cfg=cfg)
    as_of = prices["date"].iloc[-1]

    rows = evaluate_states(res, as_of, cfg, "PASSED")
    sup = next(r for r in rows if r["ticker"] == "A")
    assert sup["state"] == SUPPRESSED
    assert sup["underlying_state"] == BUY_SETUP
    assert "low sample" in sup["suppressed_reason"]


def test_signal_states_in_trade():
    closes = [100, 89, 85, 100, 100, 89, 90, 95, 95, 95]  # never recovers
    prices, res = scenario(closes)
    rows = evaluate_states(res, prices["date"].iloc[-1], ENGINE_CFG, "PASSED")
    it = next(r for r in rows if r["state"] == "IN_TRADE")
    assert it["ticker"] == "A"
    assert it["days_held"] == (prices["date"].iloc[-1] - prices["date"].iloc[6]).days
    assert it["stop_price"] is not None and it["time_stop_date"] is not None


def _random_universe(n_tickers=8, n_days=700, seed=7):
    rng = np.random.default_rng(seed)
    prices, ohlc = {}, {}
    for i in range(n_tickers):
        steps = rng.normal(0.0005, 0.025, n_days)
        closes = 100 * np.exp(np.cumsum(steps))
        p = make_prices(closes)
        prices[f"T{i}"] = p
        ohlc[f"T{i}"] = make_ohlc(p)
    return prices, ohlc


def test_signal_backtest_parity():
    """Replay the backtest period through the (shared) signal engine and check
    the emitted BUY/SELL sequence matches the trade log exactly."""
    prices, ohlc = _random_universe()
    events = {t: build_events(p, 10.0) for t, p in prices.items()}
    calendar = pd.DatetimeIndex(next(iter(prices.values()))["date"].iloc[100:])
    cfg = {**ENGINE_CFG, "top_k": 4, "max_positions": 2}  # forces skips

    res = run_engine(events, ohlc.get, calendar, cfg)
    trades, sig, skipped = res["trades"], res["signals"], res["skipped_entries"]
    assert len(trades) > 3, "fixture produced too few trades to be meaningful"

    buys = sig[sig["state"] == BUY_SETUP]
    # 1. every executed trade traces back to exactly one BUY_SETUP signal
    for _, t in trades.iterrows():
        match = buys[(buys["ticker"] == t["ticker"])
                     & (buys["date"] == t["trigger_date"])]
        assert len(match) == 1

    # 2. every BUY_SETUP (except a last-day one) became a trade or a recorded skip
    n_last_day = int((buys["date"] == calendar[-1]).sum())
    assert len(buys) == len(trades) + len(skipped) + n_last_day

    # 3. SELL signal counts match trade exit reasons one-for-one
    last = calendar[-1]
    for reason in (SELL_RECOVERY, SELL_STOP, SELL_TIME):
        n_sig = int(((sig["state"] == reason) & (sig["date"] < last)).sum()
                    if reason != SELL_STOP
                    else ((sig["state"] == reason) & (sig["date"] <= last)).sum())
        n_trd = int((trades["exit_reason"] == reason).sum())
        assert n_sig == n_trd, f"{reason}: {n_sig} signals vs {n_trd} trades"

    # 4. never more than max_positions concurrent trades
    open_spans = trades[["entry_date", "exit_date"]].values
    for day in calendar:
        n_open = int(((open_spans[:, 0] <= day) & (day < open_spans[:, 1])).sum())
        assert n_open <= cfg["max_positions"]


def test_engine_deterministic():
    prices, ohlc = _random_universe()
    events = {t: build_events(p, 10.0) for t, p in prices.items()}
    calendar = pd.DatetimeIndex(next(iter(prices.values()))["date"].iloc[100:])
    r1 = run_engine(events, ohlc.get, calendar, ENGINE_CFG)
    r2 = run_engine(events, ohlc.get, calendar, ENGINE_CFG)
    pd.testing.assert_frame_equal(r1["trades"], r2["trades"])
    pd.testing.assert_frame_equal(r1["equity_curve"], r2["equity_curve"])
