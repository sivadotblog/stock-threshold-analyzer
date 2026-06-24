#!/usr/bin/env python3
"""
Generate per-ticker JSON files consumed by the SMA static site.

Reads the top N tickers from sma/data/bullish_screen.json (produced by
screen_bullish.py) and fetches their price history from Yahoo Finance.

Run order: screen_bullish.py → generate_data.py

For each ticker:
  - Writes sma/data/{TICKER}.json:
        { "ticker": "TQQQ",
          "name": "ProShares UltraPro QQQ",
          "fetched_at": "2026-06-11T...",
          "start": "2021-06-11",
          "end":   "2026-06-10",
          "prices": [{"d": "2021-06-11", "c": 27.31}, ...]
        }

The threshold (+/-N%) is intentionally NOT precomputed — the browser recomputes
events whenever the user moves the threshold slider, so we only ship raw closes.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
import yfinance as yf

_ROOT = Path(__file__).parent
_CONFIG = yaml.safe_load((_ROOT / "config.yaml").read_text())
_SITE = _CONFIG["site"]
LOOKBACK_YEARS: int = _SITE["lookback_years"]
TOP_N: int = _SITE["top_n"]
OUTPUT_DIR = _ROOT / "sma" / "data"
SCREEN_PATH = OUTPUT_DIR / "bullish_screen.json"


def _tickers_from_screen() -> list[str]:
    if not SCREEN_PATH.exists():
        raise SystemExit(
            f"'{SCREEN_PATH}' not found — run screen_bullish.py first."
        )
    data = json.loads(SCREEN_PATH.read_text())
    tickers = [r["ticker"] for r in data["results"][:TOP_N]]
    print(f"Top {TOP_N} tickers from bullish screen: {', '.join(tickers)}")
    return tickers


def fetch_one(ticker: str, start: str, end: str) -> dict:
    print(f"  -> Fetching {ticker} ({start} to {end}) ...")
    tk = yf.Ticker(ticker)

    # Long name (best-effort; some tickers don't expose it)
    long_name = ticker
    try:
        info = tk.info or {}
        long_name = info.get("longName") or info.get("shortName") or ticker
    except Exception:  # noqa: BLE001
        pass

    hist = tk.history(start=start, end=end, auto_adjust=True)
    if hist.empty:
        raise SystemExit(f"No data returned for ticker '{ticker}'. Check the symbol.")

    prices = [
        {"d": idx.strftime("%Y-%m-%d"), "c": round(float(row["Close"]), 4)}
        for idx, row in hist.iterrows()
    ]

    return {
        "ticker": ticker,
        "name": long_name,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "start": prices[0]["d"],
        "end": prices[-1]["d"],
        "prices": prices,
    }


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tickers = _tickers_from_screen()

    end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(days=LOOKBACK_YEARS * 365)
    end = end_dt.strftime("%Y-%m-%d")
    start = start_dt.strftime("%Y-%m-%d")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lookback_years": LOOKBACK_YEARS,
        "tickers": [],
    }

    print(f"Refreshing {len(tickers)} ticker(s) into {OUTPUT_DIR}")
    for ticker in tickers:
        payload = fetch_one(ticker, start, end)
        out = OUTPUT_DIR / f"{ticker}.json"
        out.write_text(json.dumps(payload, separators=(",", ":")))
        print(f"     wrote {out} ({len(payload['prices']):,} rows)")
        manifest["tickers"].append({
            "ticker": ticker,
            "name": payload["name"],
            "start": payload["start"],
            "end": payload["end"],
            "rows": len(payload["prices"]),
        })

    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote manifest -> {OUTPUT_DIR / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
