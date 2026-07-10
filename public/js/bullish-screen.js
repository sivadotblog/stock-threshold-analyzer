/* Dip-buy leaderboard visualizer — Tabulator edition (v2)
 *
 * Primary ranking: bounce_rate_wilson_low (95% Wilson lower bound of the
 * bounce rate). The legacy v1 bullish_score is shown greyed and deprecated.
 * A validation banner (PASSED / WEAK / FAILED) gates how the table should be
 * read: without a PASSED validation, every row is descriptive, not a signal.
 */
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

  // ---- Validation banner (spec §5) ----
  function renderBanner(el, v) {
    if (!el) return;
    const status = (v && v.status) || "NOT_RUN";
    const palette = {
      PASSED: { bg: "var(--up-bg,#e0f2fe)", fg: "var(--up,#0369a1)" },
      WEAK: { bg: "#fef3c7", fg: "#92400e" },
      FAILED: { bg: "var(--down-bg,#fff7ed)", fg: "var(--down,#c2410c)" },
      NOT_RUN: { bg: "var(--border,#e2e8f0)", fg: "var(--fg-muted,#4a5568)" },
    }[status] || { bg: "#eee", fg: "#333" };

    const stats = (v && v.rho !== undefined && v.rho !== null)
      ? ` (ρ=${fmt(v.rho, 2)}, p=${fmt(v.p, 4)}, n=${v.n_tickers}; rolling median ρ=${fmt(v.rolling_median_rho, 2)})`
      : "";
    const lines = (v && v.interpretation) || [];
    el.innerHTML =
      `<div style="background:${palette.bg};color:${palette.fg};border-left:4px solid ${palette.fg};` +
      `padding:10px 14px;border-radius:6px;margin:0.75rem 0;">` +
      `<strong>Predictive validation: ${status}</strong>${stats}` +
      (status !== "PASSED"
        ? `<br><span style="font-size:0.9em;">Signals are suppressed — treat every row below as historical description, not a trade recommendation.</span>`
        : "") +
      (lines.length
        ? `<details style="margin-top:6px;"><summary style="cursor:pointer;font-size:0.85em;">interpretation</summary>` +
          `<ul style="margin:6px 0 0 1.2em;font-size:0.85em;">` +
          lines.map((l) => `<li>${l}</li>`).join("") + `</ul></details>`
        : "") +
      `</div>`;
  }

  // ---- Scatter chart ----
  function renderScatter(el, results) {
    const others = results.filter((r) => r.ticker !== HIGHLIGHT);
    const zeta = results.find((r) => r.ticker === HIGHLIGHT);

    const hover = (r) =>
      `<b>${r.ticker}</b> &nbsp;#${r.rank}<br>` +
      `Wilson low: <b>${fmt(r.bounce_rate_wilson_low, 3)}</b><br>` +
      `bounce rate: ${fmt(r.bounce_rate, 2)} (${r.n_bounces}/${r.n_bounces + r.n_continuations})<br>` +
      `median days to bounce: ${fmt(r.median_days_to_bounce, 0)} (p90 ${fmt(r.p90_days_to_bounce, 0)})<br>` +
      `median MAE: ${fmt(r.median_mae_pct, 1)}%<br>` +
      `expectancy/trade: ${fmt(r.expectancy_per_trade_pct, 2)}%<br>` +
      `CAGR: ${fmt(r.cagr_pct, 1)}%/yr`;

    const traces = [{
      type: "scattergl", mode: "markers",
      x: others.map((r) => r.expectancy_per_trade_pct),
      y: others.map((r) => r.n_down_events),
      text: others.map(hover),
      hoverinfo: "text",
      marker: {
        size: 9,
        color: others.map((r) => r.bounce_rate_wilson_low),
        colorscale: "Viridis", cmin: 0, cmax: 1,
        colorbar: { title: { text: "Wilson low" }, thickness: 14 },
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
        x: [zeta.expectancy_per_trade_pct], y: [zeta.n_down_events],
        text: ["ZETA"], textposition: "top center",
        textfont: { color: clrAccent, size: 13 },
        hoverinfo: "text", hovertext: [hover(zeta)],
        marker: { size: 20, color: clrAccent, line: { width: 1.5, color: clrBg } },
      });
    }

    Plotly.newPlot(el, traces, {
      title: { text: "Dip-buy edge — expectancy vs. evidence", font: { color: clrFg } },
      xaxis: { title: "Expectancy per -10% trigger (%)", zeroline: true, zerolinecolor: clrMuted, zerolinewidth: 1.5, gridcolor: clrBorder, color: clrFg },
      yaxis: { title: "Evidence → # down-trigger events (5y)", gridcolor: clrBorder, color: clrFg },
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

    const streakFmt = (cell) => {
      const s = cell.getValue() || 0;
      const color = s > 0 ? "var(--up,#0369a1)" : s < 0 ? "var(--down,#c2410c)" : "inherit";
      return `<span style="color:${color};font-weight:700;">${streakLabel(s)}</span>`;
    };

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

    // Signal state badge with the §5.5 context in the tooltip.
    const signalFmt = (cell) => {
      const r = cell.getRow().getData();
      const sig = r.signal;
      const state = (sig && sig.state) || "NONE";
      if (state === "NONE") return `<span style="opacity:0.35;">—</span>`;
      let tip = "";
      if (sig) {
        if (state === "SUPPRESSED") {
          tip = `would be ${sig.underlying_state || "?"} — ${sig.suppressed_reason || ""}`;
        } else if (state === "BUY_SETUP") {
          tip = `trigger ${sig.trigger_price} on ${sig.trigger_date}; actionable from ${sig.actionable_from} at the OPEN (never same-day); ` +
                `${sig.base_rate || ""}; median ${sig.median_days_to_bounce}d to bounce (p90 ${sig.p90_days_to_bounce}d); ` +
                `stop ${sig.stop_price}; time-stop ${sig.time_stop_date}; ` +
                `median MAE ${sig.median_mae_pct}% — expect it to typically get worse before resolving`;
        } else if (state === "IN_TRADE") {
          tip = `held ${sig.days_held}d vs median ${sig.median_days_to_bounce}d; stop ${sig.stop_price}; time-stop ${sig.time_stop_date}`;
        }
      }
      const style = {
        BUY_SETUP: "background:var(--up-bg,#e0f2fe);color:var(--up,#0369a1);",
        IN_TRADE: "background:#ede9fe;color:#5b21b6;",
        SELL_RECOVERY: "background:var(--up-bg,#e0f2fe);color:var(--up,#0369a1);",
        SELL_STOP: "background:var(--down-bg,#fff7ed);color:var(--down,#c2410c);",
        SELL_TIME: "background:var(--down-bg,#fff7ed);color:var(--down,#c2410c);",
        SUPPRESSED: "background:var(--border,#e2e8f0);color:var(--fg-subtle,#718096);opacity:0.8;",
      }[state] || "";
      return `<span title="${tip.replaceAll('"', "&quot;")}" style="font-size:0.72em;font-weight:700;padding:2px 7px;border-radius:20px;${style}">${state}</span>`;
    };

    const bounceFmt = (cell) => {
      const r = cell.getRow().getData();
      if (r.bounce_rate === null || r.bounce_rate === undefined)
        return `<span style="opacity:0.35;">—</span>`;
      const n = (r.n_bounces ?? 0) + (r.n_continuations ?? 0);
      return `${Number(r.bounce_rate).toFixed(2)} <span style="opacity:0.6;font-size:0.85em;">(${r.n_bounces}/${n})</span>`;
    };

    const tickerFmt = (cell) => {
      const r = cell.getRow().getData();
      const t = cell.getValue();
      const warn = r.low_sample
        ? ` <span title="low sample: only ${r.n_down_events} down events in the window" style="cursor:help;">⚠️</span>`
        : "";
      return `<a href="https://finance.yahoo.com/quote/${t}" target="_blank" rel="noopener" style="font-weight:700;color:var(--accent,#0284c7);">${t}</a>${warn}`;
    };

    const num = (d) => (cell) => fmt(cell.getValue(), d);

    tabulatorInstance = new Tabulator(el, {
      data: results,
      layout: "fitDataFill",
      pagination: true,
      paginationSize: 50,
      paginationSizeSelector: [25, 50, 100, 250],
      movableColumns: true,
      initialSort: [{ column: "bounce_rate_wilson_low", dir: "desc" }],
      columns: [
        { title: "#", field: "rank", sorter: "number", hozAlign: "right", width: 55 },
        { title: "Ticker", field: "ticker", sorter: "string", width: 105, formatter: tickerFmt },
        { title: "Signal", field: "signal_state", sorter: "string", hozAlign: "center", width: 110, formatter: signalFmt },
        { title: "Wilson low", field: "bounce_rate_wilson_low", sorter: "number", hozAlign: "right", width: 105,
          formatter: (cell) => `<b>${fmt(cell.getValue(), 3)}</b>` },
        { title: "Bounce rate", field: "bounce_rate", sorter: "number", hozAlign: "right", width: 115, formatter: bounceFmt },
        { title: "n▼", field: "n_down_events", sorter: "number", hozAlign: "right", width: 60 },
        { title: "Cens", field: "n_censored", sorter: "number", hozAlign: "right", width: 65 },
        { title: "Med days", field: "median_days_to_bounce", sorter: "number", hozAlign: "right", width: 90, formatter: num(0) },
        { title: "p90 days", field: "p90_days_to_bounce", sorter: "number", hozAlign: "right", width: 90, formatter: num(0) },
        { title: "Med MAE%", field: "median_mae_pct", sorter: "number", hozAlign: "right", width: 95, formatter: num(1) },
        { title: "Worst MAE%", field: "worst_mae_pct", sorter: "number", hozAlign: "right", width: 105, formatter: num(1) },
        { title: "Expect%", field: "expectancy_per_trade_pct", sorter: "number", hozAlign: "right", width: 90, formatter: num(2) },
        { title: "Streak", field: "current_streak", sorter: "number", hozAlign: "right", width: 90, formatter: streakFmt },
        { title: "Recent Δ", field: "recent_events", hozAlign: "center", width: 150, formatter: recentEventsFmt },
        { title: "CAGR%", field: "cagr_pct", sorter: "number", hozAlign: "right", width: 85, formatter: num(1) },
        { title: "MaxDD%", field: "max_drawdown_pct", sorter: "number", hozAlign: "right", width: 90, formatter: num(1) },
        { title: "v1 score (deprecated)", field: "bullish_score_v1", sorter: "number", hozAlign: "right", width: 150,
          formatter: (cell) => `<span style="opacity:0.45;" title="legacy v1 bullish_score — deprecated, not used for ranking">${fmt(cell.getValue(), 3)}</span>` },
        { title: "Category", field: "category", sorter: "string", minWidth: 110,
          formatter: (cell) => `<span style="color:var(--fg-muted,#4a5568);">${cell.getValue() || "—"}</span>` },
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
    if (!tabulatorInstance) return;

    function applyFilters() {
      const filters = [];
      const t = document.getElementById("f-ticker")?.value.trim();
      if (t) filters.push({ field: "ticker", type: "like", value: t });
      const rankMax = document.getElementById("f-rank-max")?.value;
      if (rankMax) filters.push({ field: "rank", type: "<=", value: Number(rankMax) });
      const wMin = document.getElementById("f-wilson-min")?.value;
      if (wMin) filters.push({ field: "bounce_rate_wilson_low", type: ">=", value: Number(wMin) });
      const nMin = document.getElementById("f-n-min")?.value;
      if (nMin) filters.push({ field: "n_down_events", type: ">=", value: Number(nMin) });
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
  function render() {
    const scatterEl = document.getElementById("bullish-scatter");
    const tableEl = document.getElementById("bullish-table");
    const metaEl = document.getElementById("bullish-meta");
    const bannerEl = document.getElementById("validation-banner");
    if (!scatterEl || typeof Plotly === "undefined" || typeof Tabulator === "undefined") return;

    fetch(`${dataBase()}/bullish_screen.json`, { cache: "no-store" })
      .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(data => {
        const results = data.results || [];
        if (metaEl) {
          metaEl.innerHTML =
            `Screened <b>${data.universe_size}</b> tickers @ ±${data.threshold_pct}% ` +
            `over ${data.lookback_years}y — <b>${results.length}</b> with events. ` +
            `<small>Generated ${new Date(data.generated_at).toLocaleString()}.</small>`;
        }
        renderBanner(bannerEl, data.validation);
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
          "Run <code>python3 main.py leaderboard</code> to generate it.</span>";
      });
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", render);
  else render();
})();
