"""
Leaderboard generation.

Rank = ``net_legs_per_year`` (n_up - n_down, per year) among trend-positive
tickers — a good oscillator needs both a favorable up/down ratio (quality)
and a high leg count (frequency); neither alone is enough, and the
subtraction fuses them without a weighted score. ``net_dips_per_year`` /
``recovery_rate`` (dip-transition reliability) stay as context columns.
Downtrenders keep their rows — the chart
explorer feeds off this list (generate_data.py) — but are flagged
``trend_positive: false`` and sorted below every positive so they never rank
as candidates. Thin histories (fewer than ``min_events`` completed legs, e.g.
a one-year-old leveraged ETF) are flagged ``thin_history: true``, and short
histories (actual price-history span below ``min_history_years`` — a
newly-listed single-stock leveraged ETF that clears ``min_events`` on
volatility-inflated chop alone, e.g. LMTL/AVGU at ~1y old) are flagged
``short_history: true``; both sort at the same tier, just below the proven
steady names — different cause (leg count vs. calendar span), same problem
(the rate has no denominator to stand on). Parabolic runners (a 3x+ spike
from a trailing 12-month low, e.g. CIFR $3 -> $25) keep their rows too but
are flagged ``parabolic: true`` and sorted below every steady trend-positive
ticker: their legs came from a one-way regime shift, not a repeatable
dip-cycle. Dip-chainers (longest run of consecutive down legs at/past the
cap, e.g. NET's 6-deep chain ~-47% from the first BUY) are flagged
``chained_dips: true`` and sorted between the steady candidates and the
parabolics: their history is real but their BUY signals routinely ride deep
underwater before harvesting. Each row carries
``current_price`` (last close) and ``action_side``/``action_price`` (the
next price level that would print a threshold event) — deliberately not a
recommendation, just a level to compare against the current price.
``pct_to_action`` is the signed distance between them (negative on a BUY
row, positive on a SELL row) so the leaderboard can be sorted by proximity
to its next event, independent of the rank order above.

Pure functions; I/O lives in the CLI.
"""

from __future__ import annotations

import pandas as pd

from reliability import (DEFAULT_CHAINED_DEEP_RUN_COUNT,
                         DEFAULT_CHAINED_DEEP_RUN_LEN,
                         DEFAULT_CHAINED_MAX_DOWN_STREAK,
                         DEFAULT_MIN_EVENTS,
                         DEFAULT_MIN_HISTORY_YEARS,
                         DEFAULT_PARABOLIC_MAX_RUN_UP_PCT,
                         DEFAULT_PARABOLIC_RECENCY_DAYS,
                         DEFAULT_PARABOLIC_WINDOW_DAYS,
                         compute_oscillation_summary)


def compute_leaderboard_rows(prices_by_ticker: dict[str, pd.DataFrame],
                             categories: dict[str, str],
                             as_of, threshold_pct: float,
                             recent_window_days: int,
                             parabolic_window_days: int = DEFAULT_PARABOLIC_WINDOW_DAYS,
                             parabolic_max_run_up_pct: float = DEFAULT_PARABOLIC_MAX_RUN_UP_PCT,
                             parabolic_recency_days: int = DEFAULT_PARABOLIC_RECENCY_DAYS,
                             chained_max_down_streak: int = DEFAULT_CHAINED_MAX_DOWN_STREAK,
                             chained_deep_run_len: int = DEFAULT_CHAINED_DEEP_RUN_LEN,
                             chained_deep_run_count: int = DEFAULT_CHAINED_DEEP_RUN_COUNT,
                             min_events: int = DEFAULT_MIN_EVENTS,
                             min_history_years: float | None = DEFAULT_MIN_HISTORY_YEARS) -> list[dict]:
    """Per-ticker oscillation summaries, sorted for ranking.

    Sort order: steady trend-positive tickers by ``net_legs_per_year`` desc,
    then thin/short histories (evidence-quality issues — too few completed
    legs, or too little calendar span for the rate to mean anything; same
    tier, either flag demotes), then dip-chainers, then parabolic
    trend-positives, then downtrenders; ties break on ticker for
    determinism. Tickers with zero threshold events are dropped (nothing to
    show).
    """
    rows = []
    for ticker in sorted(prices_by_ticker):
        s = compute_oscillation_summary(
            prices_by_ticker[ticker], threshold_pct=threshold_pct,
            as_of=pd.Timestamp(as_of).date(),
            recent_window_days=recent_window_days,
            parabolic_window_days=parabolic_window_days,
            parabolic_max_run_up_pct=parabolic_max_run_up_pct,
            parabolic_recency_days=parabolic_recency_days,
            chained_max_down_streak=chained_max_down_streak,
            chained_deep_run_len=chained_deep_run_len,
            chained_deep_run_count=chained_deep_run_count,
            min_events=min_events,
            min_history_years=min_history_years)
        if s["n_events"] == 0:
            continue
        rows.append({
            "ticker": ticker,
            "category": categories.get(ticker, ""),
            **s,
        })
    rows.sort(key=lambda r: (not r["trend_positive"], r["parabolic"],
                             r["chained_dips"],
                             r["thin_history"] or r["short_history"],
                             -r["net_legs_per_year"], r["ticker"]))
    return rows


def build_leaderboard(rows: list[dict],
                      threshold_pct: float, lookback_years: float,
                      universe_size: int,
                      generated_at: str) -> dict:
    """Assemble the JSON payload the dashboard consumes."""
    results = [{"rank": rank, **r} for rank, r in enumerate(rows, 1)]
    return {
        "generated_at": generated_at,
        "metric": "net_legs_per_year",
        "description": (
            "Oscillation leaderboard: how many more +N% harvests than -N% "
            "dips does this ticker print per year while net-trending up? "
            "Ranked by net legs per year (up legs minus down legs) — a good "
            "oscillator needs both a favorable up/down ratio and a high leg "
            "count; the subtraction rewards both without a weighted score. "
            "Net resolved dips per year and P(recovery|dip) (dip-transition "
            "reliability — did a dip chain into another dip, or resolve) "
            "are reported alongside as context. Thin histories "
            "(too few completed legs) and short histories (too little "
            "calendar span vs. the lookback window, e.g. a newly-listed "
            "leveraged ETF) are flagged and sorted below the proven steady "
            "candidates — the rate has no denominator to stand on either "
            "way; dip-chainers (runs of consecutive -N% legs at/past the caps — "
            "BUY signals that routinely ride deep underwater) sort next; "
            "parabolic runners (spiked from their trailing 12-month low past "
            "the configured cap within the recency window — legs from a "
            "one-way regime shift, not a repeatable dip-cycle) sort below "
            "those; downtrenders are kept but flagged and sorted last. "
            "Signal is "
            "the direction of the latest threshold event: down leg = BUY, "
            "up leg = SELL — acting on it is the investor's decision."),
        "threshold_pct": threshold_pct,
        "lookback_years": lookback_years,
        "universe_size": universe_size,
        "results": results,
    }
