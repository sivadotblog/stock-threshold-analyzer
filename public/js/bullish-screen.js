/* Oscillation leaderboard visualizer — Tabulator edition (v3)
 *
 * Ranking: up_legs_per_year (positive oscillations per year — each completed
 * +10% leg is one harvestable recovery) among trend-positive tickers.
 * Downtrenders are kept but greyed and ranked last. Signal is the direction
 * of the latest threshold event: down leg = BUY, up leg = SELL. Stateless —
 * acting on it is the investor's decision; there is no trade tracking.
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

  // ---- Scatter chart ----
  function renderScatter(el, results) {
    // Candidates only: downtrenders can print many up-legs while bleeding out,
    // and parabolic runners print legs from a one-way spike — both would look
    // attractive on this chart without being repeatable dip-cyclers.
    const candidates = results.filter((r) => r.trend_positive && !r.parabolic);
    const others = candidates.filter((r) => r.ticker !== HIGHLIGHT);
    const zeta = candidates.find((r) => r.ticker === HIGHLIGHT);

    const hover = (r) =>
      `<b>${r.ticker}</b> &nbsp;#${r.rank}<br>` +
      `up-legs/yr: <b>${fmt(r.up_legs_per_year, 1)}</b> (${r.n_up}▲ / ${r.n_down}▼)<br>` +
      `CAGR: ${fmt(r.cagr_pct, 1)}%/yr<br>` +
      `MaxDD: ${fmt(r.max_drawdown_pct, 1)}%<br>` +
      `last signal: ${r.signal} @ ${fmt(r.signal_price, 2)} on ${r.last_event_date} (${fmt(r.pct_since_signal, 1)}% since)`;

    const traces = [{
      type: "scattergl", mode: "markers",
      x: others.map((r) => r.cagr_pct),
      y: others.map((r) => r.up_legs_per_year),
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
        x: [zeta.cagr_pct], y: [zeta.up_legs_per_year],
        text: ["ZETA"], textposition: "top center",
        textfont: { color: clrAccent, size: 13 },
        hoverinfo: "text", hovertext: [hover(zeta)],
        marker: { size: 20, color: clrAccent, line: { width: 1.5, color: clrBg } },
      });
    }

    Plotly.newPlot(el, traces, {
      title: { text: "Positive oscillations vs growth (trend-positive tickers)", font: { color: clrFg } },
      xaxis: { title: "CAGR %/yr", zeroline: true, zerolinecolor: clrMuted, zerolinewidth: 1.5, gridcolor: clrBorder, color: clrFg },
      yaxis: { title: "+10% legs per year (harvests)", gridcolor: clrBorder, color: clrFg },
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

    const signalBadge = (s, date, price, extraTip) => {
      if (s !== "BUY" && s !== "SELL") return `<span style="opacity:0.35;">—</span>`;
      const buy = s === "BUY";
      const tip = `${buy ? "-10%" : "+10%"} leg on ${date} at ${price}.` +
                  (extraTip ? " " + extraTip : "");
      const style = buy
        ? "background:var(--up-bg,#e0f2fe);color:var(--up,#0369a1);"
        : "background:var(--down-bg,#fff7ed);color:var(--down,#c2410c);";
      return `<span title="${tip.replaceAll('"', "&quot;")}" style="font-size:0.75em;font-weight:700;padding:2px 8px;border-radius:20px;${style}">${s} @ ${fmt(price, 2)}</span>` +
             `<span style="margin-left:6px;opacity:0.55;font-size:0.78em;">${date || ""}</span>`;
    };

    // Last signal = latest threshold event (history, not a realtime state).
    const lastSignalFmt = (cell) => {
      const r = cell.getRow().getData();
      return signalBadge(cell.getValue(), r.last_event_date, r.signal_price,
        `${fmt(r.pct_since_signal, 1)}% since. Whether to act is your decision.`);
    };

    const prevSignalFmt = (cell) => {
      const r = cell.getRow().getData();
      return signalBadge(cell.getValue(), r.prev_signal_date, r.prev_signal_price);
    };

    // Where the opposite signal fires: last BUY at 100 -> "SELL ≥ 110".
    const targetFmt = (cell) => {
      const r = cell.getRow().getData();
      if (!r.target_price) return `<span style="opacity:0.35;">—</span>`;
      const sell = r.target_side === "SELL";
      const color = sell ? "var(--down,#c2410c)" : "var(--up,#0369a1)";
      return `<span style="font-weight:600;color:${color};">${r.target_side} ${sell ? "≥" : "≤"} ${fmt(r.target_price, 2)}</span>`;
    };

    const tickerFmt = (cell) => {
      const r = cell.getRow().getData();
      const t = cell.getValue();
      let warn = "";
      if (!r.trend_positive) {
        warn = ` <span title="net downtrend over the lookback — not a candidate" style="cursor:help;">📉</span>`;
      } else if (r.parabolic) {
        warn = ` <span title="parabolic run-up (${fmt(r.max_run_up_pct, 0)}% from its trailing 12-month low) — legs came from a one-way spike, not a repeatable dip-cycle; ranked below steady oscillators" style="cursor:help;">🚀</span>`;
      }
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
      initialSort: [{ column: "rank", dir: "asc" }],
      columns: [
        { title: "#", field: "rank", sorter: "number", hozAlign: "right", width: 55 },
        { title: "Ticker", field: "ticker", sorter: "string", width: 105, formatter: tickerFmt },
        { title: "Last signal", field: "signal", sorter: "string", hozAlign: "left", width: 195, formatter: lastSignalFmt },
        { title: "Prev", field: "prev_signal", sorter: "string", hozAlign: "left", width: 195, formatter: prevSignalFmt },
        { title: "Target", field: "target_price", sorter: "number", hozAlign: "left", width: 130, formatter: targetFmt },
        { title: "Up-legs/yr", field: "up_legs_per_year", sorter: "number", hozAlign: "right", width: 105,
          formatter: (cell) => `<b>${fmt(cell.getValue(), 1)}</b>` },
        { title: "n▲", field: "n_up", sorter: "number", hozAlign: "right", width: 60 },
        { title: "n▼", field: "n_down", sorter: "number", hozAlign: "right", width: 60 },
        { title: "Since%", field: "pct_since_signal", sorter: "number", hozAlign: "right", width: 85, formatter: num(1) },
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
        { title: "Streak", field: "current_streak", sorter: "number", hozAlign: "right", width: 90, formatter: streakFmt },
        { title: "Recent Δ", field: "recent_events", hozAlign: "center", width: 150, formatter: recentEventsFmt },
        { title: "Category", field: "category", sorter: "string", minWidth: 110,
          formatter: (cell) => `<span style="color:var(--fg-muted,#4a5568);">${cell.getValue() || "—"}</span>` },
      ],
      rowFormatter: (row) => {
        const d = row.getData();
        const el = row.getElement();
        if (!d.trend_positive || d.parabolic) {
          el.style.opacity = "0.45";
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
      if (oscMin) filters.push({ field: "up_legs_per_year", type: ">=", value: Number(oscMin) });
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
    if (!scatterEl || typeof Plotly === "undefined" || typeof Tabulator === "undefined") return;

    fetch(`${dataBase()}/bullish_screen.json`, { cache: "no-store" })
      .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(data => {
        const results = data.results || [];
        if (metaEl) {
          const nPos = results.filter((r) => r.trend_positive && !r.parabolic).length;
          const nPara = results.filter((r) => r.trend_positive && r.parabolic).length;
          metaEl.innerHTML =
            `Screened <b>${data.universe_size}</b> tickers @ ±${data.threshold_pct}% ` +
            `over ${data.lookback_years}y — <b>${nPos}</b> steady trend-positive candidates, ` +
            `${nPara} parabolic runners (🚀, ranked down), ` +
            `${results.filter((r) => !r.trend_positive).length} downtrenders (greyed). ` +
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
          "Run <code>python3 main.py leaderboard</code> to generate it.</span>";
      });
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", render);
  else render();
})();
