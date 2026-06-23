"""
Calibration / sanity check for the bullish-oscillation metric.

Runs `compute_bullish_oscillation` on the ZETA cohort plus reference names and
prints the ranking. Falsifiable expectation (the metric rewards UP-trend + swings):

  * ZETA on top of its cohort (the archetype),
  * crashers that still swing (AMPL/BRZE/DV/KVYO/MGNI) at the bottom,
  * steady-flat names (KO/PG) MIDDLING -- they no longer win, they don't trend up,
  * a strong bullish swinger (e.g. APP/NVDA) scores high.

If the ordering looks wrong, retune K_TREND / ACTIVITY_HALF in reliability.py
BEFORE scaling to the full universe.
"""

from price_cache import load_cached_prices
from reliability import compute_bullish_oscillation

CALIBRATION_SET = [
    "ZETA",                                   # archetype
    "KVYO", "MGNI", "BRZE", "DV", "AMPL",     # cohort (mostly crashers)
    "APP", "NVDA", "RKLB",                     # strong bullish swingers
    "KO", "PG", "JNJ",                         # steady / flat
    "TSLA", "SOFI",                            # volatile, mixed trend
]

THRESHOLD = 10.0
YEARS = 5


def main() -> int:
    rows = []
    for ticker in CALIBRATION_SET:
        prices = load_cached_prices(ticker, years=YEARS)
        if prices is None or len(prices) < 50:
            print(f"  skip {ticker}: no data")
            continue
        r = compute_bullish_oscillation(prices, threshold_pct=THRESHOLD)
        r["ticker"] = ticker
        rows.append(r)

    rows.sort(key=lambda x: x["bullish_score"], reverse=True)

    hdr = (f"{'ticker':<7}{'SCORE':>7}{'activ':>7}{'trend':>7}{'cagr%':>8}"
           f"{'maxDD%':>8}{'netRet%':>9}{'up/dn':>9}  note")
    print("\n" + hdr)
    print("-" * len(hdr))
    for r in rows:
        note = "" if not r["gated"] else f"GATED: {r['gate_reason']}"
        print(f"{r['ticker']:<7}{r['bullish_score']:>7.3f}{r['activity']:>7.3f}"
              f"{r['trend']:>7.3f}{r['cagr_pct']:>8.1f}{r['max_drawdown_pct']:>8.1f}"
              f"{r['net_return_pct']:>9.1f}"
              f"{str(r['n_up']) + '/' + str(r['n_down']):>9}  {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
