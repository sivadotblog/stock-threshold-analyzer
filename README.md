# Stock Threshold Analyzer

Analyze a stock or ETF using a **moving-anchor ±N% threshold** rule, then visualize where each ±N% event happened and detect consecutive down-trigger streaks (drawdown clusters).

Originally built to study TQQQ's ±10% behavior over 5 years — works on any ticker supported by Yahoo Finance.

## The rule

Start at the first close as the **anchor**. Walk forward day by day. Each time the close moves **>= +N%** or **<= -N%** from the current anchor, log an event and **reset the anchor to that new close**. The next ±N% trigger is computed off the new anchor — not off the original starting price.

**Example with N=10 and start=$50:**

| Price action | Event |
|---|---|
| Ranges $50–$54 | no trigger |
| Hits $55 (+10% of $50) | ✅ +10% event, new anchor = $55 |
| Next up trigger | $60.50 (+10% of $55) |
| Next down trigger | $49.50 (–10% of $55) |

## Data source

[**yfinance**](https://github.com/ranaroussi/yfinance) (Yahoo Finance) — free, no API key, widely used. Prices are auto-adjusted for splits and dividends so historical comparisons are accurate.

## Install

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Default: TQQQ, last 5 years, 10% threshold
python analyze.py --ticker TQQQ

# Custom date range + 15% threshold
python analyze.py --ticker AAPL --start 2020-01-01 --end 2025-12-31 --threshold 15

# 3-year NVDA at 20% threshold, custom output dir
python analyze.py --ticker NVDA --years 3 --threshold 20 --output-dir ./out
```

### All options

| Flag | Default | Description |
|---|---|---|
| `--ticker`, `-t` | (required) | Ticker symbol (e.g. `TQQQ`, `AAPL`, `SPY`). |
| `--years` | `5` | Lookback window in years (ignored if `--start` is set). |
| `--start` | — | Start date `YYYY-MM-DD` (overrides `--years`). |
| `--end` | today | End date `YYYY-MM-DD`. |
| `--threshold`, `-p` | `10` | Threshold percentage. |
| `--min-streak` | `3` | Minimum consecutive down-triggers to report as a streak. |
| `--output-dir`, `-o` | `output` | Directory for CSV + PNG outputs. |

## Outputs

Each run writes four files into `--output-dir`:

- `{TICKER}_{N}pct_{start}_{end}_prices.csv` — raw daily adjusted close prices.
- `{TICKER}_{N}pct_{start}_{end}_events.csv` — every ±N% trigger event (date, price, direction, % from previous anchor).
- `{TICKER}_{N}pct_{start}_{end}_down_streaks.csv` — runs of >= `--min-streak` consecutive down-triggers with start/end prices, duration in days, and total drawdown %.
- `{TICKER}_{N}pct_{start}_{end}_chart.png` — annotated price chart with colored segments (green = building toward next +N%, red = building toward next –N%) and trigger markers.

## Example: TQQQ, 5y, 10%

Running `python analyze.py --ticker TQQQ` against the Jun 2021 – Jun 2026 window yields:

- **125 threshold events** (71 up, 54 down)
- **9 streaks** of 3+ consecutive –10% triggers, six of them in 2022
- Worst streak: **Mar–Apr 2022**, four consecutive –10% drops, –41.6% in 31 days

## Methodology notes

- "Close-to-anchor" comparisons use **daily adjusted closes** only — intraday spikes don't count.
- Events compound: a +10% then a +10% means the price is up ~21% from the prior anchor's predecessor.
- The `start` row in the events file is the initial anchor, not a triggered event.
- Streak duration is calendar days from the anchor immediately before the streak began to the final down-trigger close.

## License

MIT.
