#!/usr/bin/env python3
"""
Stock Threshold Analyzer
========================

Analyzes a stock's historical price using a "moving-anchor" ±N% threshold rule.

Rule
----
Start at the first close as the anchor. Walk forward day by day. Each time the
close moves >= +N% or <= -N% from the current anchor, log an event and reset
the anchor to that new close. The next ±N% trigger is computed off the new
anchor — NOT off the original starting price.

Example with N=10 and start=$50:
  - Price ranges $50–$54  -> no trigger
  - Price hits $55        -> +10% trigger, new anchor = $55
  - Next +10% trigger     -> $60.50
  - Next -10% trigger     -> $49.50

Data source
-----------
yfinance (Yahoo Finance) — free, reliable, widely used for OHLCV history.

Usage
-----
  python analyze.py --ticker TQQQ --years 5
  python analyze.py --ticker AAPL --start 2020-01-01 --end 2025-12-31 --threshold 15
  python analyze.py --ticker NVDA --years 3 --threshold 20 --output-dir ./out
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import yfinance as yf


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_prices(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Fetch daily adjusted close prices from Yahoo Finance via yfinance.

    Returns a DataFrame with columns: date, close.
    Uses auto-adjusted prices (splits + dividends reinvested) for accuracy.
    """
    print(f"Fetching {ticker} from Yahoo Finance: {start} -> {end} ...")
    data = yf.download(
        ticker,
        start=start,
        end=end,
        auto_adjust=True,  # adjusts for splits/dividends
        progress=False,
    )
    if data.empty:
        raise SystemExit(f"No data returned for ticker '{ticker}'. Check the symbol.")

    # yfinance returns a MultiIndex when given a list; flatten if needed.
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    df = data[["Close"]].reset_index()
    df.columns = ["date", "close"]
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    print(f"  Got {len(df):,} trading days.")
    return df


# ---------------------------------------------------------------------------
# Threshold event detection
# ---------------------------------------------------------------------------

def find_threshold_events(df: pd.DataFrame, threshold_pct: float) -> pd.DataFrame:
    """Walk the price series and emit an event every time price moves
    +/- threshold_pct from the current anchor, then reset the anchor.
    """
    anchor_price = float(df.loc[0, "close"])
    anchor_date = df.loc[0, "date"]

    events = [{
        "date": anchor_date,
        "price": anchor_price,
        "direction": "start",
        "pct_from_anchor": 0.0,
    }]

    for i in range(1, len(df)):
        price = float(df.loc[i, "close"])
        date = df.loc[i, "date"]
        pct = (price - anchor_price) / anchor_price * 100

        if pct >= threshold_pct:
            events.append({
                "date": date, "price": price,
                "direction": "up", "pct_from_anchor": pct,
            })
            anchor_price = price
        elif pct <= -threshold_pct:
            events.append({
                "date": date, "price": price,
                "direction": "down", "pct_from_anchor": pct,
            })
            anchor_price = price

    return pd.DataFrame(events)


# ---------------------------------------------------------------------------
# Down-streak analysis
# ---------------------------------------------------------------------------

def find_down_streaks(events_df: pd.DataFrame, min_run: int = 3) -> pd.DataFrame:
    """Find runs of consecutive 'down' events of length >= min_run.

    For each run, capture the price/date of the anchor right before the run
    started, the price/date at the end of the run, run length, calendar
    duration, and total drawdown.
    """
    rows = events_df[events_df["direction"].isin(["up", "down"])].reset_index(drop=True)
    streaks = []
    i = 0
    while i < len(rows):
        if rows.loc[i, "direction"] == "down":
            j = i
            while j < len(rows) and rows.loc[j, "direction"] == "down":
                j += 1
            run_len = j - i
            if run_len >= min_run:
                if i == 0:
                    start_price = float(events_df.loc[0, "price"])
                    start_date = events_df.loc[0, "date"]
                else:
                    prev = rows.loc[i - 1]
                    start_price = float(prev["price"])
                    start_date = prev["date"]
                end_row = rows.loc[j - 1]
                duration = (end_row["date"] - start_date).days
                drop_pct = (end_row["price"] - start_price) / start_price * 100
                streaks.append({
                    "streak_start_date": start_date.date(),
                    "streak_start_price": round(start_price, 2),
                    "streak_end_date": end_row["date"].date(),
                    "streak_end_price": round(float(end_row["price"]), 2),
                    "num_down_triggers": run_len,
                    "duration_days": duration,
                    "total_drop_pct": round(drop_pct, 2),
                })
            i = j
        else:
            i += 1
    return pd.DataFrame(streaks)


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------

def build_chart(
    prices: pd.DataFrame,
    events: pd.DataFrame,
    ticker: str,
    threshold_pct: float,
    output_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(16, 9))

    # Light underlying price line
    ax.plot(prices["date"], prices["close"], color="#b0b0b0", linewidth=1,
            alpha=0.6, label=f"{ticker} daily close", zorder=1)

    # Colored segments between consecutive events
    for i in range(1, len(events)):
        seg_start = events.loc[i - 1, "date"]
        seg_end = events.loc[i, "date"]
        direction = events.loc[i, "direction"]
        mask = (prices["date"] >= seg_start) & (prices["date"] <= seg_end)
        color = "#16a34a" if direction == "up" else "#dc2626"
        ax.plot(prices.loc[mask, "date"], prices.loc[mask, "close"],
                color=color, linewidth=2.2, alpha=0.9, zorder=2)

    ups = events[events["direction"] == "up"]
    downs = events[events["direction"] == "down"]
    ax.scatter(ups["date"], ups["price"], color="#16a34a", s=55, zorder=5,
               edgecolor="white", linewidth=1,
               label=f"+{threshold_pct:g}% trigger ({len(ups)})")
    ax.scatter(downs["date"], downs["price"], color="#dc2626", s=55, zorder=5,
               edgecolor="white", linewidth=1,
               label=f"-{threshold_pct:g}% trigger ({len(downs)})")
    ax.scatter(events.iloc[0]["date"], events.iloc[0]["price"],
               color="#1f2937", s=70, zorder=6, marker="D",
               label="Start anchor")

    # Annotate the all-time low and all-time high event for context
    low_idx = events["price"].idxmin()
    high_idx = events["price"].idxmax()
    for idx, va in [(low_idx, "top"), (high_idx, "bottom")]:
        row = events.loc[idx]
        ax.annotate(
            f"${row['price']:.2f}\n{row['date'].strftime('%b %Y')}",
            xy=(row["date"], row["price"]),
            xytext=(0, -28 if va == "top" else 18),
            textcoords="offset points",
            fontsize=9, ha="center", va=va, fontweight="bold",
            color="#111827",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#9ca3af", lw=0.7),
        )

    start_label = prices["date"].iloc[0].strftime("%b %Y")
    end_label = prices["date"].iloc[-1].strftime("%b %Y")
    ax.set_title(
        f"{ticker} — {threshold_pct:g}% Moving-Anchor Threshold Events "
        f"({start_label} – {end_label})",
        fontsize=15, fontweight="bold", pad=12,
    )
    ax.set_xlabel("Date", fontsize=11)
    ax.set_ylabel("Close Price (USD, split/dividend-adjusted)", fontsize=11)
    ax.grid(True, alpha=0.25, linestyle="--")
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
    ax.legend(loc="upper left", framealpha=0.95, fontsize=10)

    fig.text(
        0.5, 0.01,
        f"Rule: anchor resets each time price moves ±{threshold_pct:g}% from the "
        f"previous anchor. Green = next +{threshold_pct:g}% trigger; "
        f"red = next -{threshold_pct:g}% trigger.",
        ha="center", fontsize=9, style="italic", color="#374151",
    )
    plt.tight_layout(rect=[0, 0.03, 1, 1])
    plt.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved chart -> {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Analyze ±N% moving-anchor threshold events for a stock.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--ticker", "-t", required=True,
                   help="Stock or ETF ticker symbol (e.g. TQQQ, AAPL, SPY).")
    p.add_argument("--years", type=int, default=5,
                   help="Lookback window in years (ignored if --start is given).")
    p.add_argument("--start", help="Start date YYYY-MM-DD (overrides --years).")
    p.add_argument("--end", help="End date YYYY-MM-DD (defaults to today).")
    p.add_argument("--threshold", "-p", type=float, default=10.0,
                   help="Threshold percentage (e.g. 10 for 10%%).")
    p.add_argument("--min-streak", type=int, default=3,
                   help="Minimum consecutive down-triggers to report as a streak.")
    p.add_argument("--output-dir", "-o", default="output",
                   help="Directory for CSV + PNG output.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    ticker = args.ticker.upper()

    end = args.end or datetime.today().strftime("%Y-%m-%d")
    if args.start:
        start = args.start
    else:
        start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=args.years * 365)
                 ).strftime("%Y-%m-%d")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Fetch data
    prices = fetch_prices(ticker, start, end)

    # 2. Find threshold events
    events = find_threshold_events(prices, args.threshold)
    n_up = (events["direction"] == "up").sum()
    n_down = (events["direction"] == "down").sum()
    print(f"\nThreshold events @ ±{args.threshold:g}%: "
          f"{len(events) - 1} total ({n_up} up, {n_down} down)")

    # 3. Find down streaks
    streaks = find_down_streaks(events, min_run=args.min_streak)
    print(f"Consecutive down-streaks (>= {args.min_streak} in a row): {len(streaks)}")
    if not streaks.empty:
        print("\n" + streaks.to_string(index=False))

    # 4. Save outputs
    base = f"{ticker}_{args.threshold:g}pct_{start}_{end}"
    prices_path = output_dir / f"{base}_prices.csv"
    events_path = output_dir / f"{base}_events.csv"
    streaks_path = output_dir / f"{base}_down_streaks.csv"
    chart_path = output_dir / f"{base}_chart.png"

    prices.to_csv(prices_path, index=False)
    events.to_csv(events_path, index=False)
    streaks.to_csv(streaks_path, index=False)
    print(f"\nSaved prices  -> {prices_path}")
    print(f"Saved events  -> {events_path}")
    print(f"Saved streaks -> {streaks_path}")

    # 5. Chart
    build_chart(prices, events, ticker, args.threshold, chart_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
