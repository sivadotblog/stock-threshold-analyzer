"""
Leaderboard generation (spec §5).

Primary sort is ``bounce_rate_wilson_low`` at the configured threshold — NOT
the deprecated v1 ``bullish_score``, which is still computed and shipped
(greyed in the UI) for the deprecation period. The payload carries the §3
validation verdict so the dashboard can show the honesty banner, and optional
§5.5 signal states per ticker.

Pure functions; I/O lives in the CLI.
"""

from __future__ import annotations

import pandas as pd

from metrics import compute_ticker_metrics
from reliability import compute_bullish_oscillation


def compute_leaderboard_rows(prices_by_ticker: dict[str, pd.DataFrame],
                             categories: dict[str, str],
                             as_of, threshold_pct: float,
                             window_years: float,
                             low_sample_min_events: int) -> list[dict]:
    """Per-ticker v2 metrics plus the v1 diagnostics the dashboard keeps
    (streak, recent events, CAGR/maxDD context). Sorted by wilson low, desc;
    ties break on ticker for determinism.
    """
    rows = []
    for ticker in sorted(prices_by_ticker):
        prices = prices_by_ticker[ticker]
        m = compute_ticker_metrics(
            prices, threshold_pct, as_of=as_of, window_years=window_years,
            low_sample_min_events=low_sample_min_events, include_v1=False)
        if m["n_down_events"] == 0:
            continue
        # v1 diagnostics: streak / recent-events / CAGR / maxDD survive the v1
        # gate (they are computed before it), so this also feeds the columns
        # the old dashboard already had.
        v1 = compute_bullish_oscillation(
            prices, threshold_pct=threshold_pct,
            as_of=pd.Timestamp(as_of).date())
        rows.append({
            "ticker": ticker,
            "category": categories.get(ticker, ""),
            **{k: m[k] for k in (
                "n_down_events", "n_bounces", "n_continuations", "n_censored",
                "bounce_rate", "bounce_rate_wilson_low",
                "median_days_to_bounce", "p90_days_to_bounce",
                "median_mae_pct", "worst_mae_pct",
                "expectancy_per_trade_pct", "low_sample")},
            # legacy v1 score — DEPRECATED, shown greyed, never used for ranking
            "bullish_score_v1": None if v1["gated"] else v1["bullish_score"],
            "n_up": v1["n_up"],
            "n_down": v1["n_down"],
            "current_streak": v1["current_streak"],
            "last_event_date": v1["last_event_date"],
            "recent_events": v1["recent_events"],
            "cagr_pct": v1["cagr_pct"],
            "max_drawdown_pct": v1["max_drawdown_pct"],
            "net_return_pct": v1["net_return_pct"],
            "mean_amplitude": v1["mean_amplitude"],
        })
    rows.sort(key=lambda r: (-r["bounce_rate_wilson_low"], r["ticker"]))
    return rows


def build_leaderboard(rows: list[dict],
                      threshold_pct: float, window_years: float,
                      universe_size: int,
                      generated_at: str,
                      validation: dict | None = None,
                      signal_states: list[dict] | None = None) -> dict:
    """Assemble the JSON payload the dashboard consumes."""
    signal_by_ticker = {s["ticker"]: s for s in (signal_states or [])}
    results = []
    for rank, r in enumerate(rows, 1):
        sig = signal_by_ticker.get(r["ticker"])
        results.append({
            "rank": rank, **r,
            "signal": sig,
            "signal_state": sig["state"] if sig else "NONE",
        })

    if validation is not None:
        validation_block = {
            "status": validation["status"],
            "rho": validation["split_half"].get("bounce_rate_rho"),
            "p": validation["split_half"].get("bounce_rate_p"),
            "n_tickers": validation["split_half"].get("n_tickers"),
            "rolling_median_rho": validation["rolling"].get("median_rho"),
            "interpretation": validation["interpretation"],
        }
    else:
        validation_block = {
            "status": "NOT_RUN",
            "interpretation": [
                "Validation has not been run — treat every ranking below as "
                "descriptive, not predictive. Run the `validate` command."],
        }

    return {
        "generated_at": generated_at,
        "metric": "bounce_rate_wilson_low",
        "description": (
            "Dip-buy leaderboard: given a -N% trigger, how reliably (and how "
            "fast) has this ticker recovered +N% before triggering another "
            "-N%? Ranked by the 95% Wilson lower bound of the bounce rate — "
            "small samples are penalized automatically."),
        "threshold_pct": threshold_pct,
        "lookback_years": window_years,
        "universe_size": universe_size,
        "validation": validation_block,
        "results": results,
    }
