"""
Calibration / sanity check for the oscillation reliability metric.

Runs the metric on the existing handful plus a few steady names and prints the
ranking. Per reliability_metric.md, the falsifiable expectation is:

  * steady names (KO, PG, JNJ) and SPY score reasonably / are gated cleanly,
  * leveraged / momentum names (TQQQ, TSLA, ZETA) crater on drift / mean_revert.

If that ordering looks wrong, retune the constants in reliability.py BEFORE
scaling to the full S&P 500.
"""

from research_agent import load_prices
from reliability import compute_reliability

CALIBRATION_SET = [
    "SPY", "AAPL", "MSFT", "QQQ", "META", "AMZN", "NVDA",  # mixed
    "TQQQ", "TSLA", "ZETA",                                # volatile / trending
    "KO", "PG", "JNJ",                                     # steady
]

THRESHOLD = 10.0
YEARS = 5


def main() -> int:
    rows = []
    for ticker in CALIBRATION_SET:
        try:
            prices = load_prices(ticker, years=YEARS)
            if prices is None or len(prices) < 50:
                print(f"  skip {ticker}: no data")
                continue
            r = compute_reliability(prices, threshold_pct=THRESHOLD)
            rows.append((ticker, r))
        except Exception as e:  # noqa: BLE001
            print(f"  skip {ticker}: {e}")

    rows.sort(key=lambda x: x[1]["reliability"], reverse=True)

    hdr = (f"{'ticker':<7}{'RELIAB':>8}{'regul':>7}{'amp':>7}{'drift':>7}"
           f"{'revert':>8}{'bal':>6}{'up/dn':>8}{'netRet%':>9}  note")
    print("\n" + hdr)
    print("-" * len(hdr))
    for ticker, r in rows:
        note = "" if not r["gated"] else f"GATED: {r['gate_reason']}"
        print(f"{ticker:<7}{r['reliability']:>8.3f}{r['regularity']:>7.2f}"
              f"{r['amplitude_consistency']:>7.2f}{r['drift_score']:>7.2f}"
              f"{r['mean_revert']:>8.2f}{r['balance']:>6.2f}"
              f"{str(r['n_up']) + '/' + str(r['n_down']):>8}"
              f"{r['net_return_pct']:>9.1f}  {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
