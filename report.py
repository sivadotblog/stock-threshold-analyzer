"""
Leaderboard generation.

Rank = ``up_legs_per_year`` (positive oscillations per year) among
trend-positive tickers. Downtrenders keep their rows — the chart explorer
feeds off this list (generate_data.py) — but are flagged ``trend_positive:
false`` and sorted below every positive so they never rank as candidates.
Each row carries its stateless BUY/SELL signal inline.

Pure functions; I/O lives in the CLI.
"""

from __future__ import annotations

import pandas as pd

from reliability import compute_oscillation_summary


def compute_leaderboard_rows(prices_by_ticker: dict[str, pd.DataFrame],
                             categories: dict[str, str],
                             as_of, threshold_pct: float,
                             recent_window_days: int) -> list[dict]:
    """Per-ticker oscillation summaries, sorted for ranking.

    Sort order: trend-positive tickers by ``up_legs_per_year`` desc, then
    downtrenders by the same; ties break on ticker for determinism. Tickers
    with zero threshold events are dropped (nothing to show).
    """
    rows = []
    for ticker in sorted(prices_by_ticker):
        s = compute_oscillation_summary(
            prices_by_ticker[ticker], threshold_pct=threshold_pct,
            as_of=pd.Timestamp(as_of).date(),
            recent_window_days=recent_window_days)
        if s["n_events"] == 0:
            continue
        rows.append({
            "ticker": ticker,
            "category": categories.get(ticker, ""),
            **s,
        })
    rows.sort(key=lambda r: (not r["trend_positive"],
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
            "downtrenders are kept but flagged and sorted last. Signal is "
            "the direction of the latest threshold event: down leg = BUY, "
            "up leg = SELL — acting on it is the investor's decision."),
        "threshold_pct": threshold_pct,
        "lookback_years": lookback_years,
        "universe_size": universe_size,
        "results": results,
    }
