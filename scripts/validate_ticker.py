#!/usr/bin/env python3
"""
Validate a ticker against Yahoo Finance and add it to config.yaml supplement.

Usage: uv run python scripts/validate_ticker.py TICKER

Exits 0 on success, 1 on failure.
Sets GITHUB_OUTPUT variables: added, name, reason.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import yfinance as yf
import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
# Insertion point: the blank line before the leveraged ETF sections
INSERT_BEFORE = "\n  # Leveraged ETFs"


def set_output(key: str, value: str) -> None:
    gho = os.environ.get("GITHUB_OUTPUT", "")
    if gho:
        with open(gho, "a") as f:
            f.write(f"{key}={value}\n")
    print(f"[output] {key}={value}")


def fail(reason: str) -> None:
    set_output("added", "false")
    set_output("reason", reason)
    print(f"FAIL: {reason}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        fail("No ticker provided")

    ticker = sys.argv[1].strip().upper()

    # Basic format check — letters/digits, optional dot (BRK.B) or hyphen
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,5}", ticker):
        fail(f"`{ticker}` doesn't look like a valid ticker symbol")

    # Check not already in config
    config_text = CONFIG_PATH.read_text()
    config = yaml.safe_load(config_text)
    universe = config.get("universe", {})
    existing = {str(t).upper() for tickers in universe.values() for t in tickers}
    if ticker in existing:
        fail(f"`{ticker}` is already in the screening universe")

    # Validate with Yahoo Finance — fetch recent history
    print(f"Validating {ticker} on Yahoo Finance …")
    try:
        hist = yf.Ticker(ticker).history(period="5d")
    except Exception as e:
        fail(f"Yahoo Finance error for `{ticker}`: {e}")

    if hist.empty:
        fail(f"`{ticker}` not found on Yahoo Finance (no price data returned)")

    # Get display name
    try:
        info = yf.Ticker(ticker).fast_info
        name = getattr(info, "description", "") or ticker
    except Exception:
        name = ticker

    # Prettier name fallback via .info (slower but more complete)
    try:
        long_name = yf.Ticker(ticker).info.get("longName") or yf.Ticker(ticker).info.get("shortName", "")
        if long_name:
            name = long_name
    except Exception:
        pass

    # Add to config.yaml supplement — string manipulation to preserve comments
    if INSERT_BEFORE not in config_text:
        fail("Could not find insertion point in config.yaml")

    new_text = config_text.replace(
        INSERT_BEFORE,
        f"\n    - {ticker}{INSERT_BEFORE}",
        1,
    )
    CONFIG_PATH.write_text(new_text)

    set_output("added", "true")
    set_output("name", name or ticker)
    print(f"✅ Added {ticker} ({name}) to supplement")


if __name__ == "__main__":
    main()
