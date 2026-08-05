# Everest

Oscillation analytics on a **moving-anchor ±N% threshold** rule, built for one
goal: **dip-cycle compounding** — repeated +10% harvests on stocks that
oscillate a lot while net-trending up ($10k × 1.1^~50 ≈ $1M).

- **Live site:** https://sivadotblog.github.io/everest/
- **Design record:** [PLAN.md](PLAN.md)

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

## The model

One ranking number, one filter, two context metrics — everything subjective is
left to the chart explorer:

| Piece | Definition |
|---|---|
| **Rank: `up_legs_per_year`** | completed +10% legs per year of data. Each up-leg is one realized, harvestable +10% recovery. No pairing with dips, no outcome classification — so overlapping dip clusters can't distort it. |
| **Filter: `trend_positive`** | net return over the lookback > 0. A down-trender is not a candidate no matter how nicely it swings. Downtrenders stay in the table (the chart explorer feeds off the same list) but are greyed and ranked below every positive. |
| **Context: `cagr_pct`** | growth over the lookback. |
| **Context: `max_drawdown_pct`** | volatility — the price of admission for the oscillations. |

**Consecutive down-legs are never failures.** A `-10, -10, -10, +20, …` path
is oscillation richness — the dips are the entry opportunities and the up-legs
are the harvests. Nothing in the pipeline classifies a dip as failed for being
followed by another dip. (Per-dip "days to recover" was dropped for the same
reason: with overlapping dips it spans the whole cluster and overstates, while
the actual harvests happened in between.)

## Signals (stateless)

The signal is the direction of the **latest** threshold event, nothing more:

- **`BUY`** — the last leg was −10%: price sits ≥10% below the previous anchor.
- **`SELL`** — the last leg was +10%: a harvest just completed.

It persists until the next event and carries its date, event price, and how
far price has moved since. There is **no trade tracking** — no positions,
stops, or time-outs. Acting on a signal is the investor's decision. Note the
SELL is anchor-based, not entry-based: if interim dips reset the anchor lower,
a SELL can fire below *your* entry +10% — judge it against your own position.

## Usage

```bash
uv sync

uv run python main.py analyze      # event stream + summaries → output/*.csv
uv run python main.py leaderboard  # dashboard data → public/data/bullish_screen.json
uv run python generate_data.py    # per-ticker chart data for the site
```

Common flags: `--threshold/-p 10`, `--years 5`, `--tickers ZETA,NVDA` (subset),
`--max-age-days 7` (trust an older price cache). All tunables live in
`config.yaml → analyzer` — no magic constants in code.

## Methodology notes & caveats

- **Descriptive, not predictive:** the leaderboard reports what each ticker
  actually printed over the window. Whether past oscillation frequency
  persists is your judgment call, per ticker, in the chart explorer.
- **Survivorship bias:** the universe is *today's* S&P 500 + supplements —
  tickers that cratered out of the index never enter the sample. The
  trend filter catches live downtrenders, not delistings.
- **Dividend adjustments:** prices are split- **and dividend-adjusted**
  (yfinance `auto_adjust`), which shifts historical thresholds slightly vs
  raw prices — consistent within the pipeline, but don't compare trigger
  prices to a broker chart tick-for-tick.
- **Leveraged ETFs are excluded** from the default universe (volatility decay
  makes their event statistics non-comparable). Re-include with
  `analyzer.include_leveraged: true`.
- **Young listings:** `up_legs_per_year` uses each ticker's actual data span,
  so an 18-month IPO gets a fair rate — but check `n▲` for how much evidence
  sits behind it.

## Tests

```bash
uv run pytest test_analyzer.py
```

Hand-crafted price paths with known event sequences (including the
dip-cluster case: three −10% legs then recovery counts 3▼/2▲ and marks
nothing as failed), signal derivation, trend filtering, the recent-events
window, and leaderboard ordering.

## Data source

[**yfinance**](https://github.com/ranaroussi/yfinance) (Yahoo Finance) — free,
no API key. Daily closes cached under `.cache/prices/`.

### Adding tickers to the site

Open a GitHub issue with the *add-ticker* template (or edit
`config.yaml → universe.supplement`); the daily `Refresh Data and Deploy`
workflow picks it up.

## License

MIT.
