"""
Leaderboard generation.

Rank = ``up_legs_per_year`` (positive oscillations per year) among
trend-positive tickers. Downtrenders keep their rows — the chart explorer
feeds off this list (generate_data.py) — but are flagged ``trend_positive:
false`` and sorted below every positive so they never rank as candidates.
Parabolic runners (a 3x+ spike from a trailing 12-month low, e.g. CIFR
$3 -> $25) keep their rows too but are flagged ``parabolic: true`` and sorted
below every steady trend-positive ticker: their legs came from a one-way
regime shift, not a repeatable dip-cycle. Each row carries its stateless
BUY/SELL signal inline.

Pure functions; I/O lives in the CLI.
"""

from __future__ import annotations

import pandas as pd

from reliability import (DEFAULT_PARABOLIC_MAX_RUN_UP_PCT,
                         DEFAULT_PARABOLIC_WINDOW_DAYS,
                         compute_oscillation_summary)


def compute_leaderboard_rows(prices_by_ticker: dict[str, pd.DataFrame],
                             categories: dict[str, str],
                             as_of, threshold_pct: float,
                             recent_window_days: int,
                             parabolic_window_days: int = DEFAULT_PARABOLIC_WINDOW_DAYS,
                             parabolic_max_run_up_pct: float = DEFAULT_PARABOLIC_MAX_RUN_UP_PCT) -> list[dict]:
    """Per-ticker oscillation summaries, sorted for ranking.

    Sort order: steady trend-positive tickers by ``up_legs_per_year`` desc,
    then parabolic trend-positives, then downtrenders; ties break on ticker
    for determinism. Tickers with zero threshold events are dropped (nothing
    to show).
    """
    rows = []
    for ticker in sorted(prices_by_ticker):
        s = compute_oscillation_summary(
            prices_by_ticker[ticker], threshold_pct=threshold_pct,
            as_of=pd.Timestamp(as_of).date(),
            recent_window_days=recent_window_days,
            parabolic_window_days=parabolic_window_days,
            parabolic_max_run_up_pct=parabolic_max_run_up_pct)
        if s["n_events"] == 0:
            continue
        rows.append({
            "ticker": ticker,
            "category": categories.get(ticker, ""),
            **s,
        })
    rows.sort(key=lambda r: (not r["trend_positive"], r["parabolic"],
                             -r["up_legs_per_year"], r["ticker"]))
    return rows


def build_leaderboard(rows: list[dict],
                      threshold_pct: float, lookback_years: float,
                      universe_size: int,
                      generated_at: str) -> dict:
    """Assemble the JSON payload the dashboard consumes."""
    results = [{"rank": rank, **r} for rank, r in enumerate(rows, 1)]
    return {
        "generated_at": generated_at,
        "metric": "up_legs_per_year",
        "description": (
            "Oscillation leaderboard: how many +N% legs (completed, "
            "harvestable recoveries) does this ticker print per year while "
            "net-trending up? Ranked by positive oscillations per year; "
            "parabolic runners (spiked from their trailing 12-month low past "
            "the configured cap — legs from a one-way regime shift, not a "
            "repeatable dip-cycle) are flagged and sorted below steady "
            "candidates; downtrenders are kept but flagged and sorted last. "
            "Signal is "
            "the direction of the latest threshold event: down leg = BUY, "
            "up leg = SELL — acting on it is the investor's decision."),
        "threshold_pct": threshold_pct,
        "lookback_years": lookback_years,
        "universe_size": universe_size,
        "results": results,
    }
