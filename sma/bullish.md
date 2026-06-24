# Bullish Oscillators — "Stocks like ZETA"

Stocks that **net-trend up** while swinging ±10% up and down repeatedly. Ranked by
`bullish_score` (= oscillation **activity** × signed **trend**). Each dot is a
stock; the **top-right** — strong uptrend *and* many two-sided swings — is the most
ZETA-like. **ZETA** is highlighted as the archetype.

<p id="bullish-meta"><em>Loading screen…</em></p>

<div id="bullish-scatter" style="min-height:520px;"></div>

## Leaderboard

| Field | What it means |
|---|---|
| **Score** | Composite 0–1 rating: how much this stock behaves like ZETA. Combines how often it swings ±10% *and* whether those swings are net upward. 1.0 = perfect bullish oscillator, 0 = doesn't qualify. |
| **Streak** | Current momentum. How many consecutive ±10% threshold crossings have gone the same direction. `+3↑` = the last 3 events were all up legs. `-2↓` = last 2 were down legs. Tells you where in the oscillation cycle the stock is *right now*. |
| **CAGR%** | Compound Annual Growth Rate — the annualized return over the 5-year lookback. 20% means the stock roughly doubled every ~3.5 years on average. |
| **MaxDD%** | Maximum Drawdown — the worst peak-to-trough drop over the 5 years. -80% means at some point it fell 80% from a high. High scores often come with brutal drawdowns because volatile stocks swing hard in both directions. |
| **↑/↓** | Raw count of up-legs / down-legs. How many times the stock crossed +10% from an anchor (↑) vs −10% (↓). A balanced ratio means it swings both ways, which is what the screener rewards. |

<div id="bullish-table"></div>
