# Plan v3 — oscillation-first simplification

## The grounded requirement

Goal: compound a fixed stake through repeated **+10% harvests** — $10k × 1.1^~50 ≈ $1M.
What makes a stock right for this is **how often it oscillates ±10% while net-trending up**.

Ground rules distilled from discussion (2026-07-14):

1. **Positive trend is required.** A ticker whose 5-year drift is net-down is
   not a candidate, no matter how nicely it swings.
2. **Consecutive down-legs are never failures.** `-10, -10, -10, +20, -10, +10`
   is a *good* pattern — the number of oscillations is what matters. No metric
   may penalize a dip for being followed by another dip.
3. **Frequency is the decision metric.** A "sound" stock that rarely dips is
   useless here — the opportunity never comes.
4. **Per-dip recovery-time stats are out.** With overlapping dips, "days to
   recover" from the first dip spans the whole cluster and overstates —
   meanwhile the harvests happened in between. Not computable honestly; drop it.
5. **Signals are stateless.** BUY = the latest threshold event was a −10% leg.
   SELL = the latest was a +10% leg. No trade/position tracking — acting on a
   signal is the investor's decision.
6. **Metrics stay minimal.** Keep CAGR (growth) and MaxDD (volatility) as
   context. Everything subjective (composites, Wilson bounds, regularity,
   balance, expectancy, MAE) goes — deeper investigation lives in the chart
   explorer.

## The model

- **Events** (unchanged): anchor-reset ±10% detection — every close that moves
  ±10% from the current anchor logs an event and resets the anchor.
- **Ranking key**: `up_legs_per_year` = n_up ÷ years of data. Every completed
  +10% leg is one realized, harvestable recovery — no pairing with dips, no
  outcome classification, immune to the overlapping-dip problem.
- **Filter**: `trend_positive` (5y net return > 0). Downtrenders are **kept in
  the table but greyed and ranked below all positives** — removing them would
  also remove them from the chart explorer (generate_data.py reads the
  leaderboard's results list).
- **Signal**: direction of the latest event: down-leg → `BUY`, up-leg → `SELL`,
  no events → `NONE`. Shown with the event date, event price, and % moved
  since — so a stale signal is visibly stale. Note: SELL is anchor-based, not
  entry-based; if interim dips reset the anchor lower, a SELL can fire below
  *your* entry+10% — by design, the investor judges it against their own entry.

## Leaderboard columns

| Column | Role |
|---|---|
| Signal (BUY/SELL + since date + % since) | the action state |
| **Up-legs/yr** | ranking key |
| n▲ / n▼ | raw oscillation counts (evidence, never hidden) |
| CAGR% | growth context |
| MaxDD% | volatility context |
| Streak, Recent Δ | momentum context (existing semantics) |
| Category | universe bucket |

Scatter: x = CAGR%, y = up-legs/yr, color = MaxDD% (ZETA highlighted).
No validation banner.

## What gets deleted

| File | Why |
|---|---|
| `events.py` | bounce/continuation/censored outcomes, MAE, days-to-resolution — rule 2 & 4 |
| `metrics.py` | Wilson bounds, bounce rates, expectancy, low-sample flags — rule 6 |
| `validate.py` | split-half/rolling persistence harness for a metric that no longer exists |
| `backtest.py` | portfolio engine, stops, time-stops, tax engine — rule 5 (no trades) |
| `signals.py` | engine replay, IN_TRADE / SELL_STOP / SELL_TIME / SUPPRESSED states — rule 5 |
| `screen_bullish.py`, `calibrate_*.py` | v1 composite score pipeline — rule 6 |
| `test_v2.py`, `test_reliability.py` | test the deleted machinery |

(All recoverable from git history if ever needed.)

## What changes

1. **`reliability.py`** → trimmed to `find_threshold_events` (unchanged) +
   `compute_oscillation_summary`: n_up, n_down, up_legs_per_year, span_years,
   net_return_pct, cagr_pct, max_drawdown_pct, trend_positive, current_streak,
   signal / signal_price / pct_since_signal / last_event_date, recent_events
   (existing 30-day semantics). No gates, no scores.
2. **`report.py`** → leaderboard rows from the summary. Sort: trend-positives
   by up-legs/yr desc, then downtrenders by the same; continuous rank numbers;
   signal inline on each row. No validation block.
3. **`main.py`** → two subcommands: `analyze` (events + summary CSVs to
   `output/`) and `leaderboard` (writes `public/data/bullish_screen.json`).
   `validate` / `backtest` / `signals` removed.
4. **`config.yaml`** → `v2:` and `screen:` blocks replaced by
   `analyzer: {thresholds_pct: [10.0], lookback_years: 5, recent_window_days: 30, include_leveraged: false}`.
   `site:` and `universe:` unchanged.
5. **`.github/workflows/refresh_sma_data.yml`** → drop the `validate` and
   `signals` steps; keep `leaderboard` → `generate_data.py` → Astro build.
6. **`public/js/bullish-screen.js`** → new columns per the table above,
   BUY/SELL badge with tooltip, new scatter axes, banner code removed,
   downtrend rows greyed.
7. **`src/pages/index.astro`** → intro copy, filter bar (Ticker / Rank ≤ /
   Up-legs/yr ≥ / CAGR range), field-description legend rewritten.
8. **`test_analyzer.py`** (new) → hand-crafted paths with known event
   sequences: the `-10,-10,-10,+20…` cluster counts legs and never marks a
   failure; signal derivation (last-leg direction, BUY and SELL cases);
   trend filter; leaderboard ordering (positives before downtrenders);
   recent-events window; streak.
9. **`README.md`** → rewritten around the new model (rule, ranking, signals,
   caveats: survivorship, dividend adjustment, leveraged-ETF exclusion stay).

## Unchanged

- Anchor-reset event rule and threshold (±10%).
- Chart explorer (`chart.astro`, `sma-chart.js`), price cache, universe config,
  `generate_data.py`, deploy workflow shape.
- Streak and Recent Δ column semantics (already fixed earlier).

## Defaults chosen (flag if you disagree)

- Rank by **up-legs/yr** rather than total events/yr — up-legs are the
  realized harvests; a stock still stuck in a dip cluster gets credit only
  for completed recoveries.
- Downtrenders greyed at the bottom, not removed (keeps chart-explorer data).
- A months-old signal still shows (BUY/SELL persists until the next event);
  the "since" date + % since make staleness visible.
- `span_years` uses each ticker's actual data span (an 18-month IPO with 6
  up-legs shows 4.0/yr, with n▲ = 6 visible as the evidence).
