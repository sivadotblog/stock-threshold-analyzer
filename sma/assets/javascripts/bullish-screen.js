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

  function renderTable(el, results, topN) {
    const rows = results.slice(0, topN);
    const th = (t) => `<th style="text-align:right;padding:4px 8px;">${t}</th>`;
    const td = (t, extra) =>
      `<td style="text-align:right;padding:4px 8px;${extra || ""}">${t}</td>`;

    let html =
      '<table style="border-collapse:collapse;font-size:0.85em;width:100%;">' +
      "<thead><tr>" +
      '<th style="text-align:right;padding:4px 8px;">#</th>' +
      '<th style="text-align:left;padding:4px 8px;">Ticker</th>' +
      th("Score") + th("Activity") + th("Trend") + th("CAGR %/yr") +
      th("Max DD %") + th("Swings ↑/↓") +
      "</tr></thead><tbody>";

    for (const r of rows) {
      const hot = r.ticker === HIGHLIGHT ? "background:rgba(220,38,38,0.10);" : "";
      html +=
        `<tr style="border-top:1px solid var(--md-default-fg-color--lightest);${hot}">` +
        td(r.rank) +
        `<td style="text-align:left;padding:4px 8px;font-weight:600;${hot}">${r.ticker}</td>` +
        td(`<b>${fmt(r.bullish_score, 3)}</b>`) +
        td(fmt(r.activity, 2)) +
        td(fmt(r.trend, 2)) +
        td(fmt(r.cagr_pct, 1)) +
        td(fmt(r.max_drawdown_pct, 1)) +
        td(`${r.n_up}/${r.n_down}`) +
        "</tr>";
    }
    html += "</tbody></table>";
    el.innerHTML = html;
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
        renderTable(tableEl, results, 30);
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
