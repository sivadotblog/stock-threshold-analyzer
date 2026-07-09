/* Bullish Oscillator screen visualizer — Tabulator edition */
(function () {
  "use strict";

  const HIGHLIGHT = "ZETA";

  function dataBase() {
    return window.__DATA_BASE__ || "/stock-threshold-analyzer/data";
  }

  function fmt(n, d) {
    return (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toFixed(d);
  }

  function streakLabel(n) {
    if (!n) return "—";
    return (n > 0 ? "+" : "") + n + (n > 0 ? "↑" : "↓");
  }

  // ---- Scatter chart ----
  function renderScatter(el, results) {
    const others = results.filter((r) => r.ticker !== HIGHLIGHT);
    const zeta   = results.find((r)  => r.ticker === HIGHLIGHT);

    const swings = (r) => r.n_up + r.n_down;
    const hover  = (r) =>
      `<b>${r.ticker}</b> &nbsp;#${r.rank}<br>` +
      `bullish_score: <b>${fmt(r.bullish_score, 3)}</b><br>` +
      `activity: ${fmt(r.activity, 2)} &nbsp; trend: ${fmt(r.trend, 2)}<br>` +
      `CAGR: ${fmt(r.cagr_pct, 1)}%/yr<br>` +
      `max drawdown: ${fmt(r.max_drawdown_pct, 1)}%<br>` +
      `swings: ${r.n_up}↑ / ${r.n_down}↓`;

    const cloud = {
      type: "scattergl", mode: "markers",
      x: others.map((r) => r.cagr_pct),
      y: others.map(swings),
      text: others.map(hover),
      hoverinfo: "text",
      marker: {
        size: 9,
        color: others.map((r) => r.bullish_score),
        colorscale: "Viridis", cmin: 0, cmax: 1,
        showscale: true,
        colorbar: { title: "bullish<br>score", thickness: 14 },
        line: { width: 0.5, color: "rgba(0,0,0,0.25)" },
      },
      name: "stocks",
    };

    const cs       = getComputedStyle(document.documentElement);
    const clrAccent = cs.getPropertyValue("--accent").trim()    || "#0284c7";
    const clrBg     = cs.getPropertyValue("--bg").trim()        || "#f7fafc";
    const clrFg     = cs.getPropertyValue("--fg").trim()        || "#2d3748";
    const clrBorder = cs.getPropertyValue("--border").trim()    || "#cbd5e0";
    const clrMuted  = cs.getPropertyValue("--fg-subtle").trim() || "#718096";

    const traces = [cloud];
    if (zeta) {
      traces.push({
        type: "scattergl", mode: "markers+text",
        x: [zeta.cagr_pct], y: [swings(zeta)],
        text: ["ZETA"], textposition: "top center",
        textfont: { size: 13, color: clrAccent },
        hovertext: [hover(zeta)], hoverinfo: "text",
        marker: { symbol: "star", size: 20, color: clrAccent, line: { width: 1.5, color: "white" } },
        showlegend: false,
      });
    }

    Plotly.newPlot(el, traces, {
      title: { text: "Bullish oscillators — CAGR vs. swing count", font: { color: clrFg } },
      xaxis: { title: "Trend  →  CAGR (% / yr)", zeroline: true, zerolinecolor: clrMuted, zerolinewidth: 1.5, gridcolor: clrBorder, color: clrFg },
      yaxis: { title: "Oscillation  →  # of ±10% swings (up + down)", gridcolor: clrBorder, color: clrFg },
      hovermode: "closest",
      margin: { t: 50, r: 20, b: 55, l: 60 },
      paper_bgcolor: clrBg, plot_bgcolor: clrBg, font: { color: clrFg },
      shapes: [{ type: "line", x0: 0, x1: 0, yref: "paper", y0: 0, y1: 1, line: { color: clrMuted, width: 1, dash: "dot" } }],
    }, { responsive: true, displaylogo: false });
  }

  // ---- Tabulator table ----
  let tabulatorInstance = null;

  function buildTable(el, results) {
    if (tabulatorInstance) { tabulatorInstance.destroy(); tabulatorInstance = null; }

    results.forEach(r => { r.swings = r.n_up + r.n_down; });

    const streakFmt = (cell) => {
      const s = cell.getValue() || 0;
      const color = s > 0 ? "var(--up,#0369a1)" : s < 0 ? "var(--down,#c2410c)" : "inherit";
      return `<span style="color:${color};font-weight:700;">${streakLabel(s)}</span>`;
    };

    // recent_events: every threshold-crossing event in the last N days
    // (oldest -> newest), regardless of which calendar day it landed on --
    // e.g. two down-legs then an up-leg renders as -1↓ -1↓ +1↑.
    const recentEventsFmt = (cell) => {
      const events = cell.getValue() || [];
      if (!events.length) {
        return `<span style="opacity:0.35;">—</span>`;
      }
      return events.map(ev => {
        const up  = ev.direction === "up";
        const sign  = up ? "+1↑" : "-1↓";
        const color = up ? "var(--up,#0369a1)" : "var(--down,#c2410c)";
        const bg    = up ? "var(--up-bg,#e0f2fe)" : "var(--down-bg,#fff7ed)";
        return `<span title="${ev.date}" style="font-size:0.75em;font-weight:700;padding:2px 6px;border-radius:20px;background:${bg};color:${color};">${sign}</span>`;
      }).join(" ");
    };

    tabulatorInstance = new Tabulator(el, {
      data: results,
      layout: "fitColumns",
      pagination: true,
      paginationSize: 50,
      paginationSizeSelector: [25, 50, 100, 250],
      paginationCounter: "rows",
      initialSort: [{ column: "rank", dir: "asc" }],
      columns: [
        { title: "#",       field: "rank",            sorter: "number", hozAlign: "right", width: 55 },
        { title: "Ticker",  field: "ticker",           sorter: "string", width: 95,
          formatter: (cell) => {
            const t = cell.getValue();
            return `<a href="https://finance.yahoo.com/quote/${t}" target="_blank" rel="noopener" style="font-weight:700;color:var(--accent,#0284c7);">${t}</a>`;
          }
        },
        { title: "Category", field: "category",       sorter: "string", minWidth: 110,
          formatter: (cell) => `<span style="color:var(--fg-muted,#4a5568);">${cell.getValue() || "—"}</span>` },
        { title: "Score",   field: "bullish_score",    sorter: "number", hozAlign: "right", width: 80,
          formatter: (cell) => `<b>${fmt(cell.getValue(), 3)}</b>` },
        { title: "Streak",  field: "current_streak",   sorter: "number", hozAlign: "right", width: 115,
          formatter: streakFmt },
        { title: "Recent Δ", field: "recent_events",   hozAlign: "center", width: 150,
          formatter: recentEventsFmt },
        { title: "CAGR%",  field: "cagr_pct",          sorter: "number", hozAlign: "right", width: 80,
          formatter: (cell) => fmt(cell.getValue(), 1) },
        { title: "MaxDD%", field: "max_drawdown_pct",  sorter: "number", hozAlign: "right", width: 90,
          formatter: (cell) => fmt(cell.getValue(), 1) },
        { title: "↑/↓",    field: "swings",            sorter: "number", hozAlign: "right", width: 70,
          formatter: (cell) => { const r = cell.getRow().getData(); return `${r.n_up}/${r.n_down}`; } },
      ],
      rowFormatter: (row) => {
        if (row.getData().ticker === HIGHLIGHT) {
          const el = row.getElement();
          el.style.background = "var(--accent-light,#e0f2fe)";
          el.style.borderLeft = "3px solid var(--accent,#0284c7)";
        }
      },
    });
  }

  function wireFilters() {
    function applyFilters() {
      if (!tabulatorInstance) return;
      const filters = [];
      const ticker = document.getElementById("f-ticker")?.value.trim();
      if (ticker) filters.push({ field: "ticker", type: "like", value: ticker });

      const rankMax = document.getElementById("f-rank-max")?.value;
      if (rankMax !== "") filters.push({ field: "rank", type: "<=", value: +rankMax });

      const scoreMin = document.getElementById("f-score-min")?.value;
      if (scoreMin !== "") filters.push({ field: "bullish_score", type: ">=", value: +scoreMin });

      const cagrMin = document.getElementById("f-cagr-min")?.value;
      if (cagrMin !== "") filters.push({ field: "cagr_pct", type: ">=", value: +cagrMin });
      const cagrMax = document.getElementById("f-cagr-max")?.value;
      if (cagrMax !== "") filters.push({ field: "cagr_pct", type: "<=", value: +cagrMax });

      const ddMin = document.getElementById("f-dd-min")?.value;
      if (ddMin !== "") filters.push({ field: "max_drawdown_pct", type: ">=", value: +ddMin });
      const ddMax = document.getElementById("f-dd-max")?.value;
      if (ddMax !== "") filters.push({ field: "max_drawdown_pct", type: "<=", value: +ddMax });

      tabulatorInstance.setFilter(filters);
    }

    document.querySelectorAll("#tb-filters input").forEach(inp => inp.addEventListener("input", applyFilters));
    document.getElementById("f-reset")?.addEventListener("click", () => {
      document.querySelectorAll("#tb-filters input").forEach(inp => inp.value = "");
      tabulatorInstance?.clearFilter();
    });
  }

  // ---- Bootstrap ----
  function render() {
    const scatterEl = document.getElementById("bullish-scatter");
    const tableEl   = document.getElementById("bullish-table");
    const metaEl    = document.getElementById("bullish-meta");
    if (!scatterEl || typeof Plotly === "undefined" || typeof Tabulator === "undefined") return;

    fetch(`${dataBase()}/bullish_screen.json`, { cache: "no-store" })
      .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(data => {
        const results = data.results || [];
        if (metaEl) {
          metaEl.innerHTML =
            `Screened <b>${data.universe_size}</b> tickers @ ±${data.threshold_pct}% ` +
            `over ${data.lookback_years}y — <b>${results.length}</b> eligible. ` +
            `<small>Generated ${new Date(data.generated_at).toLocaleString()}.</small>`;
        }
        renderScatter(scatterEl, results);
        buildTable(tableEl, results);
        wireFilters();
        const rerender = () => renderScatter(scatterEl, results);
        window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", rerender);
        window.addEventListener("themechange", rerender);
      })
      .catch(err => {
        if (metaEl) metaEl.innerHTML =
          `<span style="color:var(--down,#c2410c);">Could not load bullish_screen.json (${err}). ` +
          "Run <code>python3 screen_bullish.py</code> to generate it.</span>";
      });
  }

  if (document.readyState !== "loading") render();
  else document.addEventListener("DOMContentLoaded", render);
})();
