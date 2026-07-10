#!/usr/bin/env python3
"""
v2 CLI (spec §6): events/metrics -> validation -> backtest -> leaderboard -> signals.

Subcommands (each writes its artifacts under ``output/``):

  analyze      build the event stream + per-ticker §2 metrics
  validate     §3 out-of-sample harness; prints PASS/WEAK/FAIL interpretation
  backtest     §4 walk-forward dip-buy backtest (pre- and after-tax, benchmarks)
  leaderboard  emit dashboard data (public/data/bullish_screen.json)
  signals      §5.5 states at the latest close; appends output/signals_log.csv

All I/O (config, price cache, JSON/CSV artifacts) lives here — the imported
modules are pure functions on DataFrames.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).parent
OUTPUT_DIR = ROOT / "output"
SITE_DATA_DIR = ROOT / "public" / "data"
VALIDATION_PATH = OUTPUT_DIR / "validation.json"
SIGNALS_PATH = OUTPUT_DIR / "signals.json"
SIGNALS_LOG_PATH = OUTPUT_DIR / "signals_log.csv"


def _config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text())


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return str(o)[:10]
    raise TypeError(f"not JSON serializable: {type(o)}")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default))
    print(f"wrote {path}")


def _universe(cfg: dict, tickers_arg: str | None) -> tuple[list[str], dict[str, str]]:
    """Universe tickers + ticker->category map. Leveraged ETF categories are
    excluded by default (volatility decay makes their event statistics
    non-comparable) unless v2.include_leveraged is set."""
    uni = cfg["universe"]
    include_lev = cfg["v2"]["include_leveraged"]
    categories: dict[str, str] = {}
    tickers: set[str] = set()
    for cat, names in uni.items():
        for t in names:
            categories.setdefault(t, cat)
        if include_lev or not cat.startswith("leveraged"):
            tickers.update(names)
    if tickers_arg:
        tickers = {t.strip().upper() for t in tickers_arg.split(",")}
    return sorted(tickers), categories


def _load_prices(tickers: list[str], years: int, max_age_days: float) -> dict[str, pd.DataFrame]:
    from price_cache import load_cached_prices
    out = {}
    for i, t in enumerate(tickers, 1):
        df = load_cached_prices(t, years=years, max_age_days=max_age_days)
        if df is not None and len(df) >= 50:
            out[t] = df
        if i % 100 == 0:
            print(f"  ... {i}/{len(tickers)} tickers loaded")
    return out


def _build_events(prices_by_ticker: dict[str, pd.DataFrame],
                  threshold_pct: float) -> dict[str, pd.DataFrame]:
    from events import build_events
    return {t: build_events(p, threshold_pct) for t, p in prices_by_ticker.items()}


def _as_of(prices_by_ticker: dict[str, pd.DataFrame]) -> pd.Timestamp:
    return max(pd.to_datetime(p["date"].iloc[-1]) for p in prices_by_ticker.values())


def _engine_cfg(cfg: dict, threshold_pct: float, **overrides) -> dict:
    v2 = cfg["v2"]
    out = {
        "threshold_pct": threshold_pct,
        "window_years": v2["window_years"],
        "low_sample_min_events": v2["low_sample_min_events"],
        **v2["backtest"],
    }
    out.update(overrides)
    return out


def _read_validation(threshold_pct: float) -> dict | None:
    if not VALIDATION_PATH.exists():
        return None
    data = json.loads(VALIDATION_PATH.read_text())
    for entry in data:
        if entry["threshold_pct"] == threshold_pct:
            return entry
    return None


def _spy_calendar(years: int, max_age_days: float,
                  start: str | None, end: str | None) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    from price_cache import load_cached_ohlc
    spy = load_cached_ohlc("SPY", years=years, max_age_days=max_age_days)
    if spy is None:
        raise SystemExit("Could not load SPY OHLC (needed as the master calendar).")
    dates = pd.DatetimeIndex(pd.to_datetime(spy["date"])).sort_values()
    if start:
        dates = dates[dates >= pd.Timestamp(start)]
    if end:
        dates = dates[dates <= pd.Timestamp(end)]
    return spy, dates


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------

def cmd_analyze(args, cfg) -> int:
    from report import compute_leaderboard_rows
    v2 = cfg["v2"]
    tickers, _ = _universe(cfg, args.tickers)
    prices = _load_prices(tickers, args.years, args.max_age_days)
    as_of = _as_of(prices)
    print(f"{len(prices)} tickers with data, as of {as_of.date()}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    for n in ([args.threshold] if args.threshold else v2["thresholds_pct"]):
        events = _build_events(prices, n)
        ev_all = pd.concat(
            [e.assign(ticker=t) for t, e in events.items() if not e.empty],
            ignore_index=True)
        ev_path = OUTPUT_DIR / f"events_{n:g}pct.csv"
        ev_all.to_csv(ev_path, index=False)
        print(f"wrote {ev_path} ({len(ev_all)} events)")

        rows = compute_leaderboard_rows(
            prices, {}, as_of, n, v2["window_years"], v2["low_sample_min_events"])
        m_path = OUTPUT_DIR / f"metrics_{n:g}pct.csv"
        pd.DataFrame(rows).drop(columns=["recent_events"]).to_csv(m_path, index=False)
        print(f"wrote {m_path} ({len(rows)} tickers)")
    return 0


def cmd_validate(args, cfg) -> int:
    from validate import run_validation
    v2 = cfg["v2"]
    tickers, _ = _universe(cfg, args.tickers)
    prices = _load_prices(tickers, args.years, args.max_age_days)
    as_of = _as_of(prices)
    window_start = as_of - pd.Timedelta(days=v2["window_years"] * 365.25)

    results = []
    for n in ([args.threshold] if args.threshold else v2["thresholds_pct"]):
        print(f"\n=== Validation @ -{n:g}% trigger, window "
              f"{window_start.date()} .. {as_of.date()} ===")
        events = _build_events(prices, n)
        res = run_validation(events, window_start, as_of, n, v2["validation"])
        results.append(res)
        s = res["split_half"]
        print(f"split-half: rho={s['bounce_rate_rho']} (p={s['bounce_rate_p']}), "
              f"expectancy rho={s['expectancy_rho']} (p={s['expectancy_p']}), "
              f"top-quintile->top-2 frac={s['quintile_top_to_top2_frac']}, "
              f"n={s['n_tickers']}")
        r = res["rolling"]
        print(f"rolling: {r['n_steps']} steps, median rho={r['median_rho']}, "
              f"frac positive={r['frac_positive']}")
        print(f"\nStatus: {res['status']}")
        for line in res["interpretation"]:
            print(f"  * {line}")

    _write_json(VALIDATION_PATH, results)
    return 0


def cmd_backtest(args, cfg) -> int:
    from backtest import run_engine, sensitivity_grid, summarize
    from price_cache import load_cached_ohlc

    v2 = cfg["v2"]
    n = args.threshold or v2["thresholds_pct"][0]
    tickers, _ = _universe(cfg, args.tickers)
    prices = _load_prices(tickers, args.years, args.max_age_days)
    events = _build_events(prices, n)
    spy, calendar = _spy_calendar(args.years, args.max_age_days, args.start, args.end)
    if len(calendar) < 60:
        raise SystemExit("Backtest period too short (need >= ~3 months of days).")
    ecfg = _engine_cfg(cfg, n)

    def ohlc_loader(t):
        return load_cached_ohlc(t, years=args.years, max_age_days=args.max_age_days)

    print(f"Backtesting {len(events)} tickers @ -{n:g}% over "
          f"{calendar[0].date()} .. {calendar[-1].date()} ...")
    pre = run_engine(events, ohlc_loader, calendar, ecfg, tax_rate=0.0)
    post = run_engine(events, ohlc_loader, calendar, ecfg,
                      tax_rate=ecfg["tax_rate_short_term"])

    # Equal-weight benchmark: buy-and-hold of the whole selected universe.
    bench = {}
    for t in events:
        df = ohlc_loader(t)
        if df is not None:
            bench[t] = df

    report = {
        "threshold_pct": n, "config": ecfg,
        "pre_tax": summarize(pre, calendar, spy_ohlc=spy, benchmark_ohlc=bench),
        "after_tax": summarize(post, calendar),
    }

    OUTPUT_DIR.mkdir(exist_ok=True)
    trades_path = OUTPUT_DIR / "backtest_trades.csv"
    pre["trades"].to_csv(trades_path, index=False)
    print(f"wrote {trades_path} ({len(pre['trades'])} trades)")
    _write_json(OUTPUT_DIR / "backtest_report.json", report)

    print(f"\n{'':<22}{'pre-tax':>12}{'after-tax':>12}")
    for key in ("cagr_pct", "max_drawdown_pct", "final_equity", "taxes_paid"):
        print(f"{key:<22}{report['pre_tax'][key]:>12}{report['after_tax'][key]:>12}")
    p = report["pre_tax"]
    print(f"\ntrades={p['n_trades']} hit_rate={p['hit_rate']} "
          f"avg_win={p['avg_win_pct']}% avg_loss={p['avg_loss_pct']}% "
          f"exposure={p['exposure_pct']}% turnover={p['turnover_x_per_year']}x/yr")
    for name in ("benchmark_spy", "benchmark_equal_weight"):
        if name in p:
            b = p[name]
            print(f"{name}: CAGR {b['cagr_pct']}%  maxDD {b['max_drawdown_pct']}%")

    if args.sensitivity:
        print("\nSensitivity grid (pre-tax; one good cell with bad neighbors = overfit):")
        grid = sensitivity_grid(prices, ohlc_loader, calendar, ecfg,
                                v2["backtest"]["sensitivity"])
        print(grid.to_string(index=False))
        grid.to_csv(OUTPUT_DIR / "backtest_sensitivity.csv", index=False)
        print(f"wrote {OUTPUT_DIR / 'backtest_sensitivity.csv'}")
    return 0


def cmd_leaderboard(args, cfg) -> int:
    from report import build_leaderboard, compute_leaderboard_rows
    v2 = cfg["v2"]
    n = args.threshold or v2["thresholds_pct"][0]
    tickers, categories = _universe(cfg, args.tickers)
    prices = _load_prices(tickers, args.years, args.max_age_days)
    as_of = _as_of(prices)

    rows = compute_leaderboard_rows(
        prices, categories, as_of, n,
        v2["window_years"], v2["low_sample_min_events"])
    validation = _read_validation(n)
    signal_states = (json.loads(SIGNALS_PATH.read_text())
                     if SIGNALS_PATH.exists() else None)
    payload = build_leaderboard(
        rows, n, v2["window_years"], universe_size=len(tickers),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        validation=validation, signal_states=signal_states)

    hdr = (f"{'#':>3} {'ticker':<7}{'wilsonLo':>9}{'bounce':>8}{'n':>5}"
           f"{'cens':>5}{'medDays':>8}{'p90':>6}{'medMAE':>8}{'expct%':>8}{'v1':>7}")
    print("\n" + hdr + "\n" + "-" * len(hdr))
    for r in payload["results"][:25]:
        v1 = r["bullish_score_v1"]
        print(f"{r['rank']:>3} {r['ticker']:<7}{r['bounce_rate_wilson_low']:>9.3f}"
              f"{(r['bounce_rate'] if r['bounce_rate'] is not None else float('nan')):>8.2f}"
              f"{r['n_down_events']:>5}{r['n_censored']:>5}"
              f"{(r['median_days_to_bounce'] or float('nan')):>8.1f}"
              f"{(r['p90_days_to_bounce'] or float('nan')):>6.0f}"
              f"{(r['median_mae_pct'] if r['median_mae_pct'] is not None else float('nan')):>8.2f}"
              f"{(r['expectancy_per_trade_pct'] if r['expectancy_per_trade_pct'] is not None else float('nan')):>8.2f}"
              f"{(v1 if v1 is not None else float('nan')):>7.3f}")
    print(f"\nValidation banner: {payload['validation']['status']}")

    _write_json(SITE_DATA_DIR / "bullish_screen.json", payload)
    _write_json(OUTPUT_DIR / "leaderboard.json", payload)
    return 0


def cmd_signals(args, cfg) -> int:
    from backtest import run_engine
    from price_cache import load_cached_ohlc
    from signals import evaluate_states

    v2 = cfg["v2"]
    n = args.threshold or v2["thresholds_pct"][0]
    tickers, _ = _universe(cfg, args.tickers)
    prices = _load_prices(tickers, args.years, args.max_age_days)
    events = _build_events(prices, n)
    _, calendar = _spy_calendar(args.years, args.max_age_days, None, None)
    ecfg = _engine_cfg(cfg, n)

    validation = _read_validation(n)
    status = validation["status"] if validation else "NOT_RUN"

    def ohlc_loader(t):
        return load_cached_ohlc(t, years=args.years, max_age_days=args.max_age_days)

    result = run_engine(events, ohlc_loader, calendar, ecfg)
    rows = evaluate_states(result, calendar[-1], ecfg, status)

    print(f"\nSignal states @ {calendar[-1].date()} "
          f"(-{n:g}% trigger, validation: {status})")
    for r in rows:
        extra = ""
        if r["state"] == "SUPPRESSED":
            extra = f" [{r.get('underlying_state')}: {r.get('suppressed_reason')}]"
        elif r["state"] == "BUY_SETUP":
            extra = (f" trigger {r['trigger_price']} on {r['trigger_date']}, "
                     f"actionable from {r['actionable_from']} open, "
                     f"stop {r['stop_price']}, {r['base_rate']}")
        elif r["state"] == "IN_TRADE":
            extra = (f" held {r['days_held']}d "
                     f"(median bounce {r['median_days_to_bounce']}d), "
                     f"stop {r['stop_price']}, time-stop {r['time_stop_date']}")
        print(f"  {r['ticker']:<7} {r['state']:<14}{extra}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    _write_json(SIGNALS_PATH, rows)
    # Append every emitted signal so live quality can be compared with the
    # backtest's expectations later (signal-vs-realized tracking).
    log = pd.DataFrame(rows)
    log.insert(0, "emitted_at",
               datetime.now(timezone.utc).isoformat(timespec="seconds"))
    log.to_csv(SIGNALS_LOG_PATH, mode="a", index=False,
               header=not SIGNALS_LOG_PATH.exists())
    print(f"appended {len(rows)} rows -> {SIGNALS_LOG_PATH}")
    return 0


def main() -> int:
    cfg = _config()
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    for name, fn in (("analyze", cmd_analyze), ("validate", cmd_validate),
                     ("backtest", cmd_backtest), ("leaderboard", cmd_leaderboard),
                     ("signals", cmd_signals)):
        sp = sub.add_parser(name)
        sp.set_defaults(fn=fn)
        sp.add_argument("--threshold", "-p", type=float, default=None,
                        help="-N%% trigger size (default: config v2.thresholds_pct)")
        sp.add_argument("--years", type=int,
                        default=cfg["v2"]["window_years"],
                        help="price history to load")
        sp.add_argument("--tickers", default=None,
                        help="comma-separated subset instead of the universe")
        sp.add_argument("--max-age-days", type=float, default=1.0)
        if name == "backtest":
            sp.add_argument("--start", default=None)
            sp.add_argument("--end", default=None)
            sp.add_argument("--sensitivity", action="store_true",
                            help="also run the N x stop x hold sensitivity grid")
    args = p.parse_args()
    return args.fn(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
