# Stock Moment Analysis

**SMA** visualizes how often a stock crosses a configurable ±N% threshold, using a *moving anchor* — the next trigger is computed off the most recent trigger, not the original start price.

## The rule

Start at the first close as the **anchor**. Walk forward day by day. Each time the close moves **>= +N%** or **<= -N%** from the current anchor, log an event and **reset the anchor** to that new close.

Example with N = 10% and start = $50:

| Action | Trigger |
|---|---|
| Ranges $50 – $54 | none |
| Hits $55 (+10% of $50) | ✅ +10% event, anchor → $55 |
| Next up trigger | $60.50 (+10% of $55) |
| Next down trigger | $49.50 (–10% of $55) |

[**Open the interactive chart →**](chart.md)

## What you can do

- Pick a ticker from the dropdown (currently TQQQ and ZETA)
- Drag the **threshold** slider from 1% to 25% to see how trigger frequency changes
- Adjust the **minimum streak** length to find consecutive down-trigger clusters (drawdown periods)
- Zoom, pan, and hover the chart for per-point details

## Data

- **Source:** Yahoo Finance, fetched via [`yfinance`](https://github.com/ranaroussi/yfinance)
- **Prices:** daily closes, **split- and dividend-adjusted**
- **Lookback:** ~5 years
- **Refresh:** automated daily via GitHub Actions

The raw price JSON is committed to the repo, so threshold changes are recomputed in your browser — no API calls at runtime.

## Code

The analyzer CLI, data generator, and this site all live in [sivadotblog/stock-threshold-analyzer](https://github.com/sivadotblog/stock-threshold-analyzer).
