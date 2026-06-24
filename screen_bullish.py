#!/usr/bin/env python3
"""
Screen a universe for stocks that oscillate *like ZETA*.

For every ticker in config.yaml → universe (sp500 + supplement), fetch cached
prices and score them with ``compute_bullish_oscillation`` (rewards an UP-trend
with frequent two-sided +/-N% swings). Ranks by ``bullish_score`` descending and:

  * prints a leaderboard table, and
  * writes a structured ``sma/data/bullish_screen.json`` (per-stock metric array)
    for the static site.

Usage
-----
  python screen_bullish.py                       # defaults from config.yaml
  python screen_bullish.py --years 10 --top 40
  python screen_bullish.py --threshold 15 --tickers ZETA,KVYO,MGNI
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from price_cache import load_cached_prices
from reliability import compute_bullish_oscillation

_CONFIG = yaml.safe_load((Path(__file__).parent / "config.yaml").read_text())
_SCREEN = _CONFIG["screen"]
_UNI = _CONFIG["universe"]
UNIVERSE: list[str] = sorted({t for tickers in _UNI.values() for t in tickers})

OUTPUT_PATH = Path(__file__).parent / "sma" / "data" / "bullish_screen.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Find stocks that oscillate like ZETA (bullish oscillators).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--years", type=int, default=_SCREEN["lookback_years"],
                   choices=[5, 10],
                   help="Lookback window in years.")
    p.add_argument("--threshold", "-p", type=float, default=_SCREEN["threshold_pct"],
                   help="Swing threshold percentage that defines one oscillation leg.")
    p.add_argument("--top", type=int, default=_SCREEN["top"],
                   help="How many top names to print.")
    p.add_argument("--max-age-days", type=float, default=1.0,
                   help="Re-fetch a ticker if its cache is older than this.")
    p.add_argument("--tickers", default=None,
                   help="Comma-separated tickers to screen instead of the full universe.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    tickers = ([t.strip().upper() for t in args.tickers.split(",")]
               if args.tickers else UNIVERSE)

    print(f"Screening {len(tickers)} tickers @ +/-{args.threshold:g}% over "
          f"{args.years}y (first run warms the cache, be patient) ...")

    rows = []
    gated = 0
    for i, ticker in enumerate(tickers, 1):
        prices = load_cached_prices(ticker, years=args.years,
                                    max_age_days=args.max_age_days)
        if prices is None or len(prices) < 50:
            continue
        r = compute_bullish_oscillation(prices, threshold_pct=args.threshold)
        r["ticker"] = ticker
        if r["gated"]:
            gated += 1
            continue
        rows.append(r)
        if i % 50 == 0:
            print(f"  ... {i}/{len(tickers)} processed")

    rows.sort(key=lambda x: x["bullish_score"], reverse=True)

    # --- leaderboard ---
    hdr = (f"{'#':>3} {'ticker':<7}{'SCORE':>7}{'activ':>7}{'trend':>7}"
           f"{'cagr%':>8}{'maxDD%':>8}{'netRet%':>9}{'up/dn':>9}")
    print("\n" + hdr)
    print("-" * len(hdr))
    for rank, r in enumerate(rows[:args.top], 1):
        print(f"{rank:>3} {r['ticker']:<7}{r['bullish_score']:>7.3f}"
              f"{r['activity']:>7.3f}{r['trend']:>7.3f}{r['cagr_pct']:>8.1f}"
              f"{r['max_drawdown_pct']:>8.1f}{r['net_return_pct']:>9.1f}"
              f"{str(r['n_up']) + '/' + str(r['n_down']):>9}")
    print(f"\nScored {len(rows)} eligible, {gated} gated, "
          f"{len(tickers) - len(rows) - gated} skipped (no/short data).")

    # --- structured output for the site ---
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metric": "bullish_oscillation",
        "description": ("Stocks that oscillate like ZETA: net-trends up while "
                        "swinging +/-N% both ways. Ranked by bullish_score."),
        "threshold_pct": args.threshold,
        "lookback_years": args.years,
        "universe_size": len(tickers),
        "results": [
            {
                "rank": rank,
                "ticker": r["ticker"],
                "bullish_score": r["bullish_score"],
                "activity": r["activity"],
                "trend": r["trend"],
                "cagr_pct": r["cagr_pct"],
                "max_drawdown_pct": r["max_drawdown_pct"],
                "net_return_pct": r["net_return_pct"],
                "n_up": r["n_up"],
                "n_down": r["n_down"],
                "current_streak": r["current_streak"],
                "mean_amplitude": r["mean_amplitude"],
            }
            for rank, r in enumerate(rows, 1)
        ],
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {len(rows)} ranked rows -> {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
