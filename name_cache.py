"""
On-disk company-name cache for the leaderboard.

Unlike prices, names barely ever change — one flat JSON file
(``.cache/names.json``, ticker -> display name) is topped up for whatever
tickers are missing from it, not refreshed on any time-based schedule.
The directory is git-ignored, same as the price cache.
"""

from __future__ import annotations

import json
from pathlib import Path

import yfinance as yf

CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_PATH = CACHE_DIR / "names.json"


def _load_cache() -> dict[str, str]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:  # noqa: BLE001 -- corrupt cache -> start fresh
        return {}


def _save_cache(cache: dict[str, str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True))


def load_cached_names(tickers: list[str]) -> dict[str, str]:
    """ticker -> display name for every ticker in ``tickers``.

    Fetches from Yahoo Finance only for tickers missing from the on-disk
    cache; falls back to the ticker symbol itself if Yahoo has nothing (or
    the fetch fails) so callers always get a usable string, never a
    KeyError or blank.
    """
    cache = _load_cache()
    missing = [t for t in tickers if t not in cache]
    for i, t in enumerate(missing, 1):
        name = t
        try:
            info = yf.Ticker(t).info or {}
            name = info.get("longName") or info.get("shortName") or t
        except Exception:  # noqa: BLE001 -- one bad ticker can't abort the batch
            pass
        cache[t] = name
        if i % 50 == 0:
            print(f"  ... {i}/{len(missing)} names fetched")
    if missing:
        _save_cache(cache)
    return {t: cache.get(t, t) for t in tickers}
