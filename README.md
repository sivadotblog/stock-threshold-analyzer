# Stock Threshold Analyzer

Event-level dip-buy analytics on a **moving-anchor ±N% threshold** rule:
given a **−N% trigger**, how reliably — and how fast — does a ticker recover
**+N%** before triggering another −N%? Everything downstream (leaderboard,
signals, backtest) is built on that question and **gated by an out-of-sample
validation harness** that tests whether the ranking predicts anything at all.

- **Live site:** https://sivadotblog.github.io/stock-threshold-analyzer/

## The rule

Start at the first close as the **anchor**. Walk forward day by day. Each time
the close moves **≥ +N%** or **≤ −N%** from the current anchor, log an event
and **reset the anchor to that new close**. The next ±N% trigger is computed
off the new anchor — not off the original starting price.

**Example with N=10 and start=$50:**

| Price action | Event |
|---|---|
| Ranges $50–$54 | no trigger |
| Hits $55 (+10% of $50) | ✅ +10% event, new anchor = $55 |
| Next up trigger | $60.50 (+10% of $55) |
| Next down trigger | $49.50 (–10% of $55) |

## The v2 pipeline

```
events.py  →  metrics.py  →  validate.py  →  backtest.py  →  report.py / signals.py
(outcomes)     (§2 ranking)   (§3 gate)       (§4 engine)      (§5 dashboard, §5.5 states)
```

Every **down event** gets an outcome record: `bounce` (next event was the +N%
recovery), `continuation` (next event was another −N% drop), or `censored`
(never resolved — kept and counted, never dropped), plus days-to-resolution,
the **max adverse excursion** (`drawdown_beyond_trigger_pct` — how much worse
it got before resolving) and the signed resolution return.

Per ticker, over a trailing window (default 5y):

| Metric | Meaning |
|---|---|
| `n_down_events` | the denominator — reported, never hidden |
| `bounce_rate` | bounces / (bounces + continuations); censored excluded but reported as `n_censored` |
| `bounce_rate_wilson_low` | **primary ranking key** — 95% Wilson lower bound; penalizes small samples smoothly (replaces the old ≥6-event gate; `low_sample` flags n<10) |
| `median_days_to_bounce`, `p90_days_to_bounce` | how long capital is typically / worst-case stuck |
| `median_mae_pct`, `worst_mae_pct` | typical / worst additional drawdown after the trigger (sizes the stop) |
| `expectancy_per_trade_pct` | mean signed resolution return per resolved trigger, before costs |
| `bullish_score_v1` | the legacy composite — **deprecated**, shown greyed for comparison only |

### Field-name mapping vs the rewrite spec

The spec's `event_date` is the existing `date` column (kept per ground rule 1);
everything else uses the spec's names. Event direction values remain
`up` / `down` / `start`.

## Usage

```bash
uv sync

uv run python main.py analyze       # events + metrics → output/*.csv
uv run python main.py validate     # §3 harness → prints PASS/WEAK/FAIL, output/validation.json
uv run python main.py backtest     # §4 walk-forward → output/backtest_*.{csv,json}
uv run python main.py backtest --sensitivity   # + N × stop × hold grid
uv run python main.py signals      # §5.5 states at latest close, appends output/signals_log.csv
uv run python main.py leaderboard  # dashboard data → public/data/bullish_screen.json
```

Common flags: `--threshold/-p 10`, `--years 5`, `--tickers ZETA,NVDA` (subset),
`--max-age-days 7` (trust an older price cache). All tunables live in
`config.yaml → v2` — no magic constants in code.

## Validation (diagnostic, not a gate)

`validate` answers: *does past bounce_rate predict future bounce_rate across
tickers?* — split-half Spearman correlation plus a rolling 2.5y→1y variant
stepped quarterly (guards against one lucky split point). The verdict
(**PASSED / WEAK / FAILED**) is shown as a banner on the dashboard, but it is
**informational only — it does not suppress or gate any signal**.

Why not a gate: the test pools the *entire* universe (currently ~600 tickers
spanning very different sectors and leverage profiles) into a single
cross-sectional correlation. A real, sector-specific persistence pattern can
be masked by that pooling — a coherent subgroup (say, a handful of space
stocks) could have genuine out-of-sample signal even while the aggregate
universe (space + oil + leveraged ETFs + everything else) fails, because
unrelated names dilute the correlation. Treating a single universe-wide
verdict as a per-ticker kill switch would silently suppress signals that
might be perfectly good for a given ticker's actual peer group.

The only thing that suppresses a signal today is the per-ticker **low-sample
gate**: a `BUY_SETUP` renders as `SUPPRESSED` if the ticker has fewer than
`low_sample_min_events` (default 10) historical down-events to base the
statistic on. "No evidence" renders as "no signal", not a hopeful arrow.

**Planned follow-up**: a sector/industry-stratified validation harness (test
each ticker against a comparison group of similar names, not the whole
universe) would let validation legitimately gate signals again. This isn't
implemented yet — the codebase has no per-ticker sector/industry metadata,
only index-membership categories (`sp500`, `leveraged_*`, etc.) in
`config.yaml`. Adding a ticker→sector mapping is a prerequisite.

## Backtest

Walk-forward, no look-ahead: monthly as-of re-ranking (top-K by Wilson lower
bound using only prior data), entry at the **next open** after a −N% trigger
(a trigger is only knowable at the close), exits on +N% recovery / hard stop
at 1.5× median MAE below the trigger / 30-day time stop, equal-weight slots,
10 bps per side, benchmarks (SPY and equal-weight universe buy-and-hold),
pre-tax and after-tax (35% short-term, applied annually to net realized gains,
paid out of the account so it compounds) side by side, full per-trade CSV, and
a sensitivity grid.

## Methodology notes & caveats

- **No look-ahead, structurally:** metric functions take an explicit `as_of`
  and filter `date <= as_of` internally; events resolved after `as_of` are
  re-censored. A unit test plants a future event and asserts it doesn't leak.
- **Survivorship bias:** the universe is *today's* S&P 500 + supplements —
  tickers that cratered out of the index never enter the sample, which
  flatters bounce rates. Treat absolute levels with suspicion; the validation
  harness (cross-sectional, within-sample-period) is partially robust to this,
  but the backtest CAGR is not.
- **Regime dependence:** persistence measured on one 5-year window reflects
  that window's regime. A PASSED verdict is not a law of nature; re-run
  `validate` as data accrues.
- **Dividend adjustments:** prices are split- **and dividend-adjusted**
  (yfinance `auto_adjust`), which shifts historical threshold triggers
  slightly vs raw prices — consistent within the pipeline, but don't compare
  trigger prices to a broker chart tick-for-tick.
- **Leveraged ETFs are excluded** from the default universe (volatility decay
  makes their event statistics non-comparable). Re-include with
  `v2.include_leveraged: true`.
- **Determinism:** same inputs → same outputs; the only stochastic piece (the
  permutation p-value) is seeded.
- **Signal log:** `signals` appends every emitted state to
  `output/signals_log.csv` for live-vs-backtest tracking. The CI job's runner
  is ephemeral, so durable logging means running `signals` locally (or
  extending CI to commit the log).

## Tests

```bash
uv run pytest test_v2.py test_reliability.py
```

Synthetic fixtures with known event sequences (pure sine → bounce_rate 1,
monotonic decline → 0 + censoring, mixed hand-crafted path), Wilson bound
reference values, MAE and censoring handling, the look-ahead leak test, engine
mechanics (fills, costs, stops, taxes), determinism, and the
**signal/backtest parity test** (the trade log and the emitted BUY/SELL
sequence must match exactly — both run the same day-step engine).

## Data source

[**yfinance**](https://github.com/ranaroussi/yfinance) (Yahoo Finance) — free,
no API key. Daily closes cached under `.cache/prices/` (close-only for
metrics, OHLC for the backtest/signal engine).

## Legacy v1

`screen_bullish.py` (the "oscillates like ZETA" `bullish_score` screen) still
runs, but its score is deprecated: it measured whether dips *already* resolved
upward over the lookback — descriptive and survivorship-shaped, not
predictive. It remains visible (greyed) on the dashboard during the
deprecation period.

### Adding tickers to the site

Open a GitHub issue with the *add-ticker* template (or edit
`config.yaml → universe.supplement`); the daily `Refresh Data and Deploy`
workflow picks it up.

## License

MIT.
