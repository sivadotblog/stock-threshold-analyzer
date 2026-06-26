/* Bullish Oscillator screen visualizer.
 *
 * Loads data/bullish_screen.json (produced by screen_bullish.py) and renders:
 *   - a Plotly scatter (CAGR vs. number of two-sided swings, colored by
 *     bullish_score) with ZETA highlighted as the archetype, and
 *   - a ranked leaderboard table.
 *
 * Follows the same Material-instant-nav pattern as reports.md / sma-chart.js.
 */

(function () {
  "use strict";

  const HIGHLIGHT = "ZETA";

  // Resolve .../sma/data regardless of whether we're at .../sma/bullish/ etc.
  function dataBase() {
    const here = window.location.pathname.replace(/\/+$/, "");
    const trimmed = here.replace(/\/bullish(\/index\.html)?$/, "");
    return trimmed + "/data";
  }

  function fmt(n, d) {
    return (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toFixed(d);
  }

  function renderScatter(el, results) {
    const others = results.filter((r) => r.ticker !== HIGHLIGHT);
    const zeta = results.find((r) => r.ticker === HIGHLIGHT);

    const swings = (r) => r.n_up + r.n_down;
    const hover = (r) =>
      `<b>${r.ticker}</b> &nbsp;#${r.rank}<br>` +
      `bullish_score: <b>${fmt(r.bullish_score, 3)}</b><br>` +
      `activity: ${fmt(r.activity, 2)} &nbsp; trend: ${fmt(r.trend, 2)}<br>` +
      `CAGR: ${fmt(r.cagr_pct, 1)}%/yr<br>` +
      `max drawdown: ${fmt(r.max_drawdown_pct, 1)}%<br>` +
      `swings: ${r.n_up}↑ / ${r.n_down}↓`;

    const cloud = {
      type: "scattergl",
      mode: "markers",
      x: others.map((r) => r.cagr_pct),
      y: others.map(swings),
      text: others.map(hover),
      hoverinfo: "text",
      marker: {
        size: 9,
        color: others.map((r) => r.bullish_score),
        colorscale: "Viridis",
        cmin: 0,
        cmax: 1,
        showscale: true,
        colorbar: { title: "bullish<br>score", thickness: 14 },
        line: { width: 0.5, color: "rgba(0,0,0,0.25)" },
      },
      name: "stocks",
    };

    const traces = [cloud];
    const annotations = [];
    if (zeta) {
      traces.push({
        type: "scattergl",
        mode: "markers+text",
        x: [zeta.cagr_pct],
        y: [swings(zeta)],
        text: ["ZETA"],
        textposition: "top center",
        textfont: { size: 13, color: "#dc2626" },
        hovertext: [hover(zeta)],
        hoverinfo: "text",
        marker: {
          symbol: "star",
          size: 20,
          color: "#dc2626",
          line: { width: 1, color: "white" },
        },
        name: "ZETA (archetype)",
        showlegend: false,
      });
    }

    const layout = {
      title: { text: "Bullish oscillators — CAGR vs. swing count" },
      xaxis: {
        title: "Trend  →  CAGR (% / yr)",
        zeroline: true,
        zerolinecolor: "#9ca3af",
        zerolinewidth: 1.5,
      },
      yaxis: { title: "Oscillation  →  # of ±10% swings (up + down)" },
      hovermode: "closest",
      margin: { t: 50, r: 20, b: 55, l: 60 },
      shapes: [
        {
          type: "line", x0: 0, x1: 0, yref: "paper", y0: 0, y1: 1,
          line: { color: "#9ca3af", width: 1, dash: "dot" },
        },
      ],
      annotations: annotations,
    };

    Plotly.newPlot(el, traces, layout, { responsive: true, displaylogo: false });
  }

  function streakLabel(n) {
    if (!n) return "—";
    return (n > 0 ? "+" : "") + n + (n > 0 ? "↑" : "↓");
  }

  // Sort state
  let sortCol = "rank";
  let sortAsc = true;

  const COLS = [
    { key: "rank",            label: "#",      left: false, val: (r) => r.rank },
    { key: "ticker",          label: "Ticker", left: true,  val: (r) => r.ticker },
    { key: "bullish_score",   label: "Score",  left: false, val: (r) => r.bullish_score },
    { key: "current_streak",  label: "Streak", left: false, val: (r) => r.current_streak || 0 },
    { key: "cagr_pct",        label: "CAGR%",  left: false, val: (r) => r.cagr_pct },
    { key: "max_drawdown_pct",label: "MaxDD%", left: false, val: (r) => r.max_drawdown_pct },
    { key: "swings",          label: "↑/↓",   left: false, val: (r) => r.n_up + r.n_down },
  ];

  function sortedResults(results) {
    const col = COLS.find((c) => c.key === sortCol);
    if (!col) return results;
    return [...results].sort((a, b) => {
      const av = col.val(a), bv = col.val(b);
      return sortAsc
        ? (av < bv ? -1 : av > bv ? 1 : 0)
        : (av > bv ? -1 : av < bv ? 1 : 0);
    });
  }

  function renderTable(el, results) {
    const S = "text-align:right;padding:3px 6px;white-space:nowrap;";
    const L = "text-align:left;padding:3px 6px;white-space:nowrap;";
    const TH = "cursor:pointer;user-select:none;";

    const sorted = sortedResults(results);

    const headers = COLS.map((c) => {
      const arrow = c.key === sortCol ? (sortAsc ? " ▲" : " ▼") : "";
      const align = c.left ? L : S;
      return `<th data-col="${c.key}" style="${align}${TH}font-weight:600;">${c.label}${arrow}</th>`;
    }).join("");

    let html =
      '<div style="overflow-x:auto;">' +
      '<table style="border-collapse:collapse;font-size:0.82em;width:100%;">' +
      `<thead><tr>${headers}</tr></thead><tbody>`;

    for (const r of sorted) {
      const hot = r.ticker === HIGHLIGHT ? "background:rgba(220,38,38,0.10);" : "";
      const streak = r.current_streak || 0;
      const streakColor = streak > 0 ? "color:#16a34a;" : streak < 0 ? "color:#dc2626;" : "";
      html +=
        `<tr style="border-top:1px solid var(--md-default-fg-color--lightest);${hot}">` +
        `<td style="${S}">${r.rank}</td>` +
        `<td style="${L}font-weight:600;"><a href="https://finance.yahoo.com/quote/${r.ticker}" target="_blank" rel="noopener">${r.ticker}</a></td>` +
        `<td style="${S}"><b>${fmt(r.bullish_score, 3)}</b></td>` +
        `<td style="${S}${streakColor}font-weight:600;">${streakLabel(streak)}</td>` +
        `<td style="${S}">${fmt(r.cagr_pct, 1)}</td>` +
        `<td style="${S}">${fmt(r.max_drawdown_pct, 1)}</td>` +
        `<td style="${S}">${r.n_up}/${r.n_down}</td>` +
        "</tr>";
    }
    html += "</tbody></table></div>";
    el.innerHTML = html;

    // Wire up header clicks
    el.querySelectorAll("th[data-col]").forEach((th) => {
      th.addEventListener("click", () => {
        const col = th.dataset.col;
        if (sortCol === col) {
          sortAsc = !sortAsc;
        } else {
          sortCol = col;
          sortAsc = col === "rank" || col === "ticker";
        }
        renderTable(el, results);
      });
    });
  }

  function render() {
    const scatterEl = document.getElementById("bullish-scatter");
    const tableEl = document.getElementById("bullish-table");
    const metaEl = document.getElementById("bullish-meta");
    if (!scatterEl || typeof Plotly === "undefined") return; // not on this page

    fetch(`${dataBase()}/bullish_screen.json`, { cache: "no-store" })
      .then((resp) => {
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        return resp.json();
      })
      .then((data) => {
        const results = data.results || [];
        const when = new Date(data.generated_at).toLocaleString();
        if (metaEl) {
          metaEl.innerHTML =
            `Screened <b>${data.universe_size}</b> tickers @ ±${data.threshold_pct}% ` +
            `over ${data.lookback_years}y — <b>${results.length}</b> eligible. ` +
            `<small>Generated ${when}.</small>`;
        }
        renderScatter(scatterEl, results);
        renderTable(tableEl, results);
      })
      .catch((err) => {
        if (metaEl) {
          metaEl.innerHTML =
            `<span style="color:red;">Could not load bullish_screen.json (${err}). ` +
            "Run <code>python3 screen_bullish.py</code> to generate it.</span>";
        }
      });
  }

  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(render);
  } else {
    document.addEventListener("DOMContentLoaded", render);
  }
})();
