/* Oscillation leaderboard visualizer — Tabulator edition (v3)
 *
 * Ranking: net_legs_per_year ((n_up - n_down) / years — surplus of harvests
 * over dips) among trend-positive tickers. Downtrenders are kept but greyed
 * and ranked last. Each row shows current_price (last close) and
 * action_side/action_price (the next price level that would print a
 * threshold event) — deliberately not a "signal": it's a level to compare
 * against the current price, not a recommendation. Stateless — there is no
 * trade tracking.
 */
(function () {
  "use strict";

  const HIGHLIGHT = "ZETA";

  function dataBase() {
    return window.__DATA_BASE__ || "/everest/data";
  }

  function siteBase() {
    return dataBase().replace(/\/data$/, "");
  }

  function fmt(n, d) {
    return (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toFixed(d);
  }

  // ---- Scatter chart ----
  function renderScatter(el, results) {
    // Candidates only: downtrenders can print many up-legs while bleeding out,
    // parabolic runners print legs from a one-way spike, dip-chainers inflate
    // their leg count by riding deep BUY chains, and thin/short histories
    // have no denominator (too few legs, or too little calendar span) —
    // all would look attractive here without being repeatable dip-cyclers.
    const candidates = results.filter((r) =>
      r.trend_positive && !r.parabolic && !r.chained_dips &&
      !r.thin_history && !r.short_history);
    const others = candidates.filter((r) => r.ticker !== HIGHLIGHT);
    const zeta = candidates.find((r) => r.ticker === HIGHLIGHT);

    const hover = (r) =>
      `<b>${r.ticker}</b> &nbsp;#${r.rank}<br>` +
      `net legs/yr: <b>${fmt(r.net_legs_per_year, 1)}</b> (${r.n_up}▲ / ${r.n_down}▼)<br>` +
      `net dips/yr: ${fmt(r.net_dips_per_year, 1)} — P(rec) ${r.recovery_rate == null ? "—" : fmt(r.recovery_rate, 2)}<br>` +
      `CAGR: ${fmt(r.cagr_pct, 1)}%/yr<br>` +
      `MaxDD: ${fmt(r.max_drawdown_pct, 1)}%<br>` +
      `price: ${fmt(r.current_price, 2)}` +
      (r.action_side ? ` — next: ${r.action_side} ${r.action_side === "SELL" ? "≥" : "≤"} ${fmt(r.action_price, 2)} (${fmt(r.pct_to_action, 1)}% away)` : "");

    const traces = [{
      type: "scattergl", mode: "markers",
      x: others.map((r) => r.cagr_pct),
      y: others.map((r) => r.net_legs_per_year),
      text: others.map(hover),
      hoverinfo: "text",
      marker: {
        size: 9,
        color: others.map((r) => r.max_drawdown_pct),
        colorscale: "Viridis", cmin: -100, cmax: 0,
        colorbar: { title: { text: "MaxDD%" }, thickness: 14 },
        opacity: 0.75, line: { width: 0.5, color: "rgba(0,0,0,0.25)" },
      },
    }];

    const cs = getComputedStyle(document.documentElement);
    const clrAccent = cs.getPropertyValue("--accent").trim() || "#0284c7";
    const clrBg = cs.getPropertyValue("--bg").trim() || "#ffffff";
    const clrFg = cs.getPropertyValue("--fg").trim() || "#1a202c";
    const clrBorder = cs.getPropertyValue("--border").trim() || "#e2e8f0";
    const clrMuted = cs.getPropertyValue("--fg-subtle").trim() || "#718096";

    if (zeta) {
      traces.push({
        type: "scattergl", mode: "markers+text",
        x: [zeta.cagr_pct], y: [zeta.net_legs_per_year],
        text: ["ZETA"], textposition: "top center",
        textfont: { color: clrAccent, size: 13 },
        hoverinfo: "text", hovertext: [hover(zeta)],
        marker: { size: 20, color: clrAccent, line: { width: 1.5, color: clrBg } },
      });
    }

    Plotly.newPlot(el, traces, {
      title: { text: "Net oscillation surplus vs growth (trend-positive tickers)", font: { color: clrFg } },
      xaxis: { title: "CAGR %/yr", zeroline: true, zerolinecolor: clrMuted, zerolinewidth: 1.5, gridcolor: clrBorder, color: clrFg },
      yaxis: { title: "net legs per year (up minus down)", gridcolor: clrBorder, color: clrFg },
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

    const recentEventsFmt = (cell) => {
      const events = cell.getValue() || [];
      if (!events.length) return `<span style="opacity:0.35;">—</span>`;
      return events.map((ev) => {
        const up = ev.direction === "up";
        const sign = up ? "+1↑" : "-1↓";
        const color = up ? "var(--up,#0369a1)" : "var(--down,#c2410c)";
        const bg = up ? "var(--up-bg,#e0f2fe)" : "var(--down-bg,#fff7ed)";
        return `<span title="${ev.date}" style="font-size:0.75em;font-weight:700;padding:2px 6px;border-radius:20px;background:${bg};color:${color};">${sign}</span>`;
      }).join(" ");
    };

    // The next price level that would print a threshold event — not a
    // recommendation, just a level to compare against current_price.
    const actionFmt = (cell) => {
      const r = cell.getRow().getData();
      if (!r.action_side) return `<span style="opacity:0.35;">—</span>`;
      const sell = r.action_side === "SELL";
      const color = sell ? "var(--down,#c2410c)" : "var(--up,#0369a1)";
      return `<span title="the next price level that would print a threshold event, based on the last completed leg on ${r.last_event_date || "—"}. Not a recommendation." style="font-weight:600;color:${color};cursor:help;">${r.action_side} ${sell ? "≥" : "≤"} ${fmt(r.action_price, 2)}</span>`;
    };

    const tickerFmt = (cell) => {
      const r = cell.getRow().getData();
      const t = cell.getValue();
      let warn = "";
      if (!r.trend_positive) {
        warn = ` <span title="net downtrend over the lookback — not a candidate" style="cursor:help;">📉</span>`;
      } else if (r.parabolic) {
        warn = ` <span title="parabolic run-up (${fmt(r.recent_run_up_pct ?? r.max_run_up_pct, 0)}% from a trailing 12-month low within the last 2 years) — legs came from a one-way spike, not a repeatable dip-cycle; ranked below steady oscillators" style="cursor:help;">🚀</span>`;
      } else if (r.chained_dips) {
        warn = ` <span title="chained dips (worst run: ${r.max_down_streak} consecutive down legs; ${r.deep_down_runs ?? "?"} runs of 4+) — BUY signals routinely ride deep underwater before harvesting; ranked below clean oscillators" style="cursor:help;">⛓️</span>`;
      } else if (r.thin_history) {
        warn = ` <span title="thin history (only ${r.n_events} completed legs) — not enough evidence for the rates to mean anything; ranked below proven oscillators" style="cursor:help;">🌱</span>`;
      } else if (r.short_history) {
        warn = ` <span title="short history (only ${fmt(r.span_years, 1)}y of price data) — the rate is computed over a span this ticker never lived through; ranked below proven oscillators" style="cursor:help;">🐣</span>`;
      }
      const chartUrl = `${siteBase()}/chart/?ticker=${encodeURIComponent(t)}`;
      return `<a href="${chartUrl}" target="_blank" rel="noopener" style="font-weight:700;color:var(--accent,#0284c7);">${t}</a>${warn}`;
    };

    const num = (d) => (cell) => fmt(cell.getValue(), d);

    tabulatorInstance = new Tabulator(el, {
      data: results,
      layout: "fitDataFill",
      pagination: true,
      paginationSize: 50,
      paginationSizeSelector: [25, 50, 100, 250],
      movableColumns: true,
      initialSort: [{ column: "rank", dir: "asc" }],
      columns: [
        { title: "#", field: "rank", sorter: "number", hozAlign: "right", width: 55 },
        { title: "Ticker", field: "ticker", sorter: "string", width: 105, formatter: tickerFmt },
        { title: "Price", field: "current_price", sorter: "number", hozAlign: "right", width: 90, formatter: num(2) },
        { title: "Action", field: "action_price", sorter: "number", hozAlign: "left", width: 130, formatter: actionFmt },
        { title: "% Needed", field: "pct_to_action", sorter: "number", hozAlign: "right", width: 100,
          formatter: (cell) => {
            const r = cell.getRow().getData();
            const v = cell.getValue();
            if (v == null) return `<span style="opacity:0.35;">—</span>`;
            const color = r.action_side === "SELL" ? "var(--down,#c2410c)" : "var(--up,#0369a1)";
            return `<span title="price must move this much to reach the Action level" style="color:${color};font-weight:600;cursor:help;">${v > 0 ? "+" : ""}${fmt(v, 1)}%</span>`;
          } },
        { title: "Net legs/yr", field: "net_legs_per_year", sorter: "number", hozAlign: "right", width: 110,
          formatter: (cell) => `<b>${fmt(cell.getValue(), 1)}</b>` },
        { title: "Net dips/yr", field: "net_dips_per_year", sorter: "number", hozAlign: "right", width: 105,
          formatter: num(1) },
        { title: "P(rec)", field: "recovery_rate", sorter: "number", hozAlign: "right", width: 80,
          formatter: (cell) => {
            const v = cell.getValue();
            return v == null ? `<span style="opacity:0.35;">—</span>` : fmt(v, 2);
          } },
        { title: "n▲", field: "n_up", sorter: "number", hozAlign: "right", width: 60 },
        { title: "n▼", field: "n_down", sorter: "number", hozAlign: "right", width: 60 },
        { title: "CAGR%", field: "cagr_pct", sorter: "number", hozAlign: "right", width: 85, formatter: num(1) },
        { title: "MaxDD%", field: "max_drawdown_pct", sorter: "number", hozAlign: "right", width: 90, formatter: num(1) },
        { title: "1y run↑%", field: "max_run_up_pct", sorter: "number", hozAlign: "right", width: 95,
          formatter: (cell) => {
            const r = cell.getRow().getData();
            const v = fmt(cell.getValue(), 0);
            return r.parabolic
              ? `<span style="color:var(--down,#c2410c);font-weight:700;">${v} 🚀</span>`
              : v;
          } },
        { title: "Recent Δ", field: "recent_events", hozAlign: "center", width: 150, formatter: recentEventsFmt },
        { title: "Category", field: "category", sorter: "string", minWidth: 110,
          formatter: (cell) => `<span style="color:var(--fg-muted,#4a5568);">${cell.getValue() || "—"}</span>` },
      ],
      rowFormatter: (row) => {
        const d = row.getData();
        const el = row.getElement();
        if (!d.trend_positive || d.parabolic) {
          el.style.opacity = "0.45";
        } else if (d.chained_dips || d.thin_history || d.short_history) {
          el.style.opacity = "0.65";
        }
        if (d.ticker === HIGHLIGHT) {
          el.style.background = "var(--accent-light,#e0f2fe)";
          el.style.borderLeft = "3px solid var(--accent,#0284c7)";
        }
      },
    });
  }

  function wireFilters() {
    if (!tabulatorInstance) return;

    function applyFilters() {
      const filters = [];
      const t = document.getElementById("f-ticker")?.value.trim();
      if (t) filters.push({ field: "ticker", type: "like", value: t });
      const rankMax = document.getElementById("f-rank-max")?.value;
      if (rankMax) filters.push({ field: "rank", type: "<=", value: Number(rankMax) });
      const oscMin = document.getElementById("f-osc-min")?.value;
      if (oscMin) filters.push({ field: "net_legs_per_year", type: ">=", value: Number(oscMin) });
      const cagrMin = document.getElementById("f-cagr-min")?.value;
      if (cagrMin) filters.push({ field: "cagr_pct", type: ">=", value: Number(cagrMin) });
      const cagrMax = document.getElementById("f-cagr-max")?.value;
      if (cagrMax) filters.push({ field: "cagr_pct", type: "<=", value: Number(cagrMax) });
      tabulatorInstance.setFilter(filters);
    }

    document.querySelectorAll("#tb-filters input").forEach(inp => inp.addEventListener("input", applyFilters));
    document.getElementById("f-reset")?.addEventListener("click", () => {
      document.querySelectorAll("#tb-filters input").forEach(inp => inp.value = "");
      tabulatorInstance?.clearFilter();
    });
  }

  // ---- Bootstrap ----
  let lastResults = [];
  let defaultThreshold = 10;
  const screenCache = new Map(); // thresholdPct -> payload

  async function loadManifest() {
    const url = `${dataBase()}/screen_manifest.json`;
    const resp = await fetch(url, { cache: "no-cache" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status} loading ${url}`);
    return await resp.json();
  }

  async function loadScreen(thresholdPct) {
    if (screenCache.has(thresholdPct)) return screenCache.get(thresholdPct);
    const url = `${dataBase()}/bullish_screen_${thresholdPct}pct.json`;
    const resp = await fetch(url, { cache: "no-store" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status} loading ${url}`);
    const data = await resp.json();
    screenCache.set(thresholdPct, data);
    return data;
  }

  function renderMeta(metaEl, data) {
    const results = data.results || [];
    const nPos = results.filter((r) => r.trend_positive && !r.parabolic && !r.chained_dips && !r.thin_history && !r.short_history).length;
    const nPara = results.filter((r) => r.trend_positive && r.parabolic).length;
    const nChain = results.filter((r) => r.trend_positive && !r.parabolic && r.chained_dips).length;
    const nThin = results.filter((r) => r.trend_positive && !r.parabolic && !r.chained_dips && r.thin_history).length;
    const nShort = results.filter((r) => r.trend_positive && !r.parabolic && !r.chained_dips && !r.thin_history && r.short_history).length;
    metaEl.innerHTML =
      `Screened <b>${data.universe_size}</b> tickers @ ±${data.threshold_pct}% ` +
      `over ${data.lookback_years}y — <b>${nPos}</b> steady trend-positive candidates, ` +
      `${nThin} thin histories (🌱, ranked down), ` +
      `${nShort} short histories (🐣, ranked down), ` +
      `${nChain} dip-chainers (⛓️, ranked down), ` +
      `${nPara} parabolic runners (🚀, ranked down), ` +
      `${results.filter((r) => !r.trend_positive).length} downtrenders (greyed). ` +
      `<small>Generated ${new Date(data.generated_at).toLocaleString()}.</small>`;
  }

  async function loadAndRender(thresholdPct, isFallback) {
    const scatterEl = document.getElementById("bullish-scatter");
    const tableEl = document.getElementById("bullish-table");
    const metaEl = document.getElementById("bullish-meta");
    if (!scatterEl || typeof Plotly === "undefined" || typeof Tabulator === "undefined") return;

    try {
      const data = await loadScreen(thresholdPct);
      lastResults = data.results || [];
      if (metaEl) renderMeta(metaEl, data);
      renderScatter(scatterEl, lastResults);
      buildTable(tableEl, lastResults);
    } catch (err) {
      if (!isFallback && thresholdPct !== defaultThreshold) {
        const thresholdInput = document.getElementById("lb-threshold");
        const thresholdLabel = document.getElementById("lb-threshold-label");
        if (thresholdInput) thresholdInput.value = defaultThreshold;
        if (thresholdLabel) thresholdLabel.textContent = `${defaultThreshold}%`;
        return loadAndRender(defaultThreshold, true);
      }
      if (metaEl) metaEl.innerHTML =
        `<span style="color:var(--down,#c2410c);">Could not load bullish_screen_${thresholdPct}pct.json (${err.message || err}). ` +
        "Run <code>python3 main.py leaderboard</code> to generate it.</span>";
    }
  }

  async function init() {
    const scatterEl = document.getElementById("bullish-scatter");
    if (!scatterEl) return;

    const thresholdInput = document.getElementById("lb-threshold");
    const thresholdLabel = document.getElementById("lb-threshold-label");

    if (thresholdInput) {
      try {
        const manifest = await loadManifest();
        if (typeof manifest.default === "number") defaultThreshold = manifest.default;
        if (Array.isArray(manifest.thresholds) && manifest.thresholds.length) {
          thresholdInput.min = Math.min(...manifest.thresholds);
          thresholdInput.max = Math.max(...manifest.thresholds);
        }
      } catch (e) {
        // Manifest missing: fall back to the slider's markup defaults (5-20, default 10).
      }
      thresholdInput.value = defaultThreshold;
      if (thresholdLabel) thresholdLabel.textContent = `${defaultThreshold}%`;

      thresholdInput.addEventListener("input", () => {
        const n = parseFloat(thresholdInput.value);
        if (thresholdLabel) thresholdLabel.textContent = `${n}%`;
        loadAndRender(n, false);
      });
    }

    await loadAndRender(defaultThreshold, false);
    wireFilters();

    const rerenderScatter = () => renderScatter(scatterEl, lastResults);
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", rerenderScatter);
    window.addEventListener("themechange", rerenderScatter);
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
