"""
On-disk price cache for the bullish-oscillator screen.

Screening several hundred tickers hits Yahoo hard, so cache each ticker's
split/dividend-adjusted daily closes to disk and only re-fetch when stale.

Cache layout: ``.cache/prices/{TICKER}_{years}y.csv`` (two columns: date, close).
The directory is git-ignored.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf


def _load_prices(ticker: str, years: int) -> Optional[pd.DataFrame]:
    end = datetime.utcnow()
    start = end - timedelta(days=years * 365)
    hist = yf.Ticker(ticker).history(
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        auto_adjust=True,
    )
    if hist.empty:
        return None
    df = hist[["Close"]].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df.reset_index().rename(columns={"Date": "date", "Close": "close"})
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df

CACHE_DIR = Path(__file__).parent / ".cache" / "prices"
_FETCH_THROTTLE_SEC = 0.4   # be polite to Yahoo on big batches


def _cache_path(ticker: str, years: int) -> Path:
    return CACHE_DIR / f"{ticker.upper()}_{years}y.csv"


def _age_days(path: Path) -> float:
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - mtime).total_seconds() / 86400.0


def load_cached_prices(ticker: str, years: int = 5,
                       max_age_days: float = 1.0) -> Optional[pd.DataFrame]:
    """Return a ['date','close'] frame for ``ticker``, from cache when fresh.

    Reads the cache file if it exists and is younger than ``max_age_days``;
    otherwise fetches live via ``load_prices``, writes the cache, and returns it.
    Returns ``None`` (never raises) if the live fetch fails or yields no data, so
    one bad ticker can't abort a batch screen.
    """
    path = _cache_path(ticker, years)

    if path.exists() and _age_days(path) <= max_age_days:
        try:
            df = pd.read_csv(path, parse_dates=["date"])
            if not df.empty:
                return df
        except Exception:  # noqa: BLE001 -- corrupt cache -> fall through to refetch
            pass

    try:
        time.sleep(_FETCH_THROTTLE_SEC)
        df = _load_prices(ticker, years=years)
    except Exception:  # noqa: BLE001
        return None
    if df is None or df.empty:
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        df.to_csv(path, index=False)
    except Exception:  # noqa: BLE001 -- caching is best-effort
        pass
    return df


def _ohlc_cache_path(ticker: str, years: int) -> Path:
    return CACHE_DIR / f"{ticker.upper()}_{years}y_ohlc.csv"


def load_cached_ohlc(ticker: str, years: int = 5,
                     max_age_days: float = 1.0) -> Optional[pd.DataFrame]:
    """Like ``load_cached_prices`` but with the full adjusted OHLC bar:
    ['date','open','high','low','close']. Needed by the v2 backtest/signal
    engine (next-open fills, intraday stop checks). Cached separately as
    ``{TICKER}_{years}y_ohlc.csv``. Returns ``None`` on any failure.
    """
    path = _ohlc_cache_path(ticker, years)

    if path.exists() and _age_days(path) <= max_age_days:
        try:
            df = pd.read_csv(path, parse_dates=["date"])
            if not df.empty:
                return df
        except Exception:  # noqa: BLE001 -- corrupt cache -> fall through to refetch
            pass

    end = datetime.utcnow()
    start = end - timedelta(days=years * 365)
    try:
        time.sleep(_FETCH_THROTTLE_SEC)
        hist = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=True,
        )
    except Exception:  # noqa: BLE001
        return None
    if hist.empty:
        return None

    df = hist[["Open", "High", "Low", "Close"]].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df.reset_index().rename(columns={
        "Date": "date", "Open": "open", "High": "high",
        "Low": "low", "Close": "close",
    })
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        df.to_csv(path, index=False)
    except Exception:  # noqa: BLE001 -- caching is best-effort
        pass
    return df


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "ZETA"
    out = load_cached_prices(sym)
    print(f"{sym}: {0 if out is None else len(out)} rows -> {_cache_path(sym, 5)}")
