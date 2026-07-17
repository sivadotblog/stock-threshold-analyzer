#!/usr/bin/env python3
"""
CLI: oscillation analytics -> leaderboard.

Subcommands:

  analyze      dump the raw ±N% event stream + per-ticker summaries -> output/*.csv
  leaderboard  build dashboard data -> public/data/bullish_screen.json

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


def _sanitize(o):
    """Replace NaN/Inf with None recursively — json.dumps serializes plain
    Python float('nan') as a literal NaN (invalid JSON) without ever calling
    the ``default`` hook, so this must run on values, not just unknown types."""
    if isinstance(o, dict):
        return {k: _sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_sanitize(v) for v in o]
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_sanitize(payload), indent=2,
                               default=_json_default, allow_nan=False))
    print(f"wrote {path}")


def _universe(cfg: dict, tickers_arg: str | None) -> tuple[list[str], dict[str, str]]:
    """Universe tickers + ticker->category map. Leveraged ETF categories are
    excluded by default (volatility decay makes their event statistics
    non-comparable) unless analyzer.include_leveraged is set."""
    uni = cfg["universe"]
    include_lev = cfg["analyzer"]["include_leveraged"]
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


def _as_of(prices_by_ticker: dict[str, pd.DataFrame]) -> pd.Timestamp:
    return max(pd.to_datetime(p["date"].iloc[-1]) for p in prices_by_ticker.values())


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------

def cmd_analyze(args, cfg) -> int:
    from reliability import find_threshold_events
    from report import compute_leaderboard_rows
    a = cfg["analyzer"]
    tickers, categories = _universe(cfg, args.tickers)
    prices = _load_prices(tickers, args.years, args.max_age_days)
    as_of = _as_of(prices)
    print(f"{len(prices)} tickers with data, as of {as_of.date()}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    for n in ([args.threshold] if args.threshold else a["thresholds_pct"]):
        frames = []
        for t, p in prices.items():
            p = p.reset_index(drop=True).copy()
            p["date"] = pd.to_datetime(p["date"], format="mixed", dayfirst=False)
            frames.append(find_threshold_events(p, n).assign(ticker=t))
        ev_all = pd.concat([f for f in frames if not f.empty], ignore_index=True)
        ev_path = OUTPUT_DIR / f"events_{n:g}pct.csv"
        ev_all.to_csv(ev_path, index=False)
        print(f"wrote {ev_path} ({len(ev_all)} events)")

        rows = compute_leaderboard_rows(
            prices, categories, as_of, n, a["recent_window_days"],
            a["parabolic_window_days"], a["parabolic_max_run_up_pct"])
        m_path = OUTPUT_DIR / f"summary_{n:g}pct.csv"
        pd.DataFrame(rows).drop(columns=["recent_events"]).to_csv(m_path, index=False)
        print(f"wrote {m_path} ({len(rows)} tickers)")
    return 0


def cmd_leaderboard(args, cfg) -> int:
    from report import build_leaderboard, compute_leaderboard_rows
    a = cfg["analyzer"]
    n = args.threshold or a["thresholds_pct"][0]
    tickers, categories = _universe(cfg, args.tickers)
    prices = _load_prices(tickers, args.years, args.max_age_days)
    as_of = _as_of(prices)

    rows = compute_leaderboard_rows(
        prices, categories, as_of, n, a["recent_window_days"],
        a["parabolic_window_days"], a["parabolic_max_run_up_pct"])
    payload = build_leaderboard(
        rows, n, args.years, universe_size=len(tickers),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    hdr = (f"{'#':>3} {'ticker':<7}{'signal':<7}{'up/yr':>7}{'n▲':>5}{'n▼':>5}"
           f"{'cagr%':>8}{'maxDD%':>8}{'run↑%':>8}{'streak':>7}  trend")
    print("\n" + hdr + "\n" + "-" * len(hdr))
    for r in payload["results"][:25]:
        trend = ("DOWN" if not r["trend_positive"]
                 else "PARA" if r["parabolic"] else "up")
        print(f"{r['rank']:>3} {r['ticker']:<7}{r['signal']:<7}"
              f"{r['up_legs_per_year']:>7.1f}{r['n_up']:>5}{r['n_down']:>5}"
              f"{r['cagr_pct']:>8.1f}{r['max_drawdown_pct']:>8.1f}"
              f"{r['max_run_up_pct']:>8.1f}"
              f"{r['current_streak']:>7}  {trend}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    _write_json(SITE_DATA_DIR / "bullish_screen.json", payload)
    _write_json(OUTPUT_DIR / "leaderboard.json", payload)
    return 0


def main() -> int:
    cfg = _config()
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    for name, fn in (("analyze", cmd_analyze), ("leaderboard", cmd_leaderboard)):
        sp = sub.add_parser(name)
        sp.set_defaults(fn=fn)
        sp.add_argument("--threshold", "-p", type=float, default=None,
                        help="±N%% leg size (default: config analyzer.thresholds_pct)")
        sp.add_argument("--years", type=int,
                        default=cfg["analyzer"]["lookback_years"],
                        help="price history to load")
        sp.add_argument("--tickers", default=None,
                        help="comma-separated subset instead of the universe")
        sp.add_argument("--max-age-days", type=float, default=1.0)
    args = p.parse_args()
    return args.fn(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
