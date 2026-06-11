/* SMA — Stock Moment Analysis
 *
 * Loads per-ticker JSON (raw daily closes) and renders an interactive
 * Plotly chart with a "moving-anchor +/-N% threshold" overlay. Threshold,
 * ticker, and date range are controlled by UI inputs and recomputed live
 * in the browser; no server round-trips after the initial JSON fetch.
 */

(function () {
  "use strict";

  // ---------- Configuration ----------
  // Resolve the data directory relative to the current page. With MkDocs
  // Material's "use_directory_urls" we may be at .../sma/ or .../sma/chart/.
  // Both should resolve to .../sma/data/.
  function dataBase() {
    const here = window.location.pathname.replace(/\/+$/, "");
    // Trim trailing /chart or /chart/index.html if present
    const trimmed = here.replace(/\/chart(\/index\.html)?$/, "");
    return trimmed + "/data";
  }

  // Cache of fetched JSON payloads by ticker
  const cache = new Map();

  async function loadManifest() {
    const url = `${dataBase()}/manifest.json`;
    const resp = await fetch(url, { cache: "no-cache" });
    if (!resp.ok) throw new Error(`Failed to load manifest: ${resp.status}`);
    return await resp.json();
  }

  async function loadTicker(ticker) {
    if (cache.has(ticker)) return cache.get(ticker);
    const url = `${dataBase()}/${ticker}.json`;
    const resp = await fetch(url, { cache: "no-cache" });
    if (!resp.ok) throw new Error(`Failed to load ${ticker}: ${resp.status}`);
    const data = await resp.json();
    cache.set(ticker, data);
    return data;
  }

  // ---------- Moving-anchor threshold detection ----------
  function detectEvents(prices, thresholdPct) {
    if (!prices.length) return [];
    let anchor = prices[0].c;
    const events = [
      { d: prices[0].d, c: anchor, dir: "start", pct: 0 },
    ];
    for (let i = 1; i < prices.length; i++) {
      const c = prices[i].c;
      const pct = ((c - anchor) / anchor) * 100;
      if (pct >= thresholdPct) {
        events.push({ d: prices[i].d, c, dir: "up", pct });
        anchor = c;
      } else if (pct <= -thresholdPct) {
        events.push({ d: prices[i].d, c, dir: "down", pct });
        anchor = c;
      }
    }
    return events;
  }

  function findDownStreaks(events, minRun) {
    const rows = events.filter((e) => e.dir === "up" || e.dir === "down");
    const streaks = [];
    let i = 0;
    while (i < rows.length) {
      if (rows[i].dir === "down") {
        let j = i;
        while (j < rows.length && rows[j].dir === "down") j++;
        const runLen = j - i;
        if (runLen >= minRun) {
          const startEvt = i === 0 ? events[0] : rows[i - 1];
          const endEvt = rows[j - 1];
          const days =
            (Date.parse(endEvt.d) - Date.parse(startEvt.d)) /
            (1000 * 60 * 60 * 24);
          const drop = ((endEvt.c - startEvt.c) / startEvt.c) * 100;
          streaks.push({
            start_date: startEvt.d,
            start_price: startEvt.c,
            end_date: endEvt.d,
            end_price: endEvt.c,
            runs: runLen,
            days: Math.round(days),
            drop_pct: drop,
          });
        }
        i = j;
      } else {
        i++;
      }
    }
    return streaks;
  }

  // ---------- Rendering ----------
  function buildTraces(prices, events) {
    // Base grey price line
    const traces = [
      {
        x: prices.map((p) => p.d),
        y: prices.map((p) => p.c),
        type: "scatter",
        mode: "lines",
        name: "Daily close",
        line: { color: "#9ca3af", width: 1.2 },
        hovertemplate: "%{x|%b %d, %Y}<br>$%{y:.2f}<extra></extra>",
      },
    ];

    // Colored segments between consecutive events
    const priceByDate = new Map(prices.map((p) => [p.d, p.c]));
    const dateIdx = new Map(prices.map((p, i) => [p.d, i]));
    for (let i = 1; i < events.length; i++) {
      const segStart = events[i - 1].d;
      const segEnd = events[i].d;
      const dir = events[i].dir;
      const a = dateIdx.get(segStart);
      const b = dateIdx.get(segEnd);
      if (a === undefined || b === undefined) continue;
      const seg = prices.slice(a, b + 1);
      traces.push({
        x: seg.map((p) => p.d),
        y: seg.map((p) => p.c),
        type: "scatter",
        mode: "lines",
        line: { color: dir === "up" ? "#16a34a" : "#dc2626", width: 2.2 },
        showlegend: false,
        hoverinfo: "skip",
      });
    }

    // Trigger markers
    const ups = events.filter((e) => e.dir === "up");
    const downs = events.filter((e) => e.dir === "down");
    traces.push({
      x: ups.map((e) => e.d),
      y: ups.map((e) => e.c),
      type: "scatter",
      mode: "markers",
      name: `+N% triggers (${ups.length})`,
      marker: { color: "#16a34a", size: 9, line: { color: "white", width: 1 } },
      hovertemplate:
        "+trigger<br>%{x|%b %d, %Y}<br>$%{y:.2f}<extra></extra>",
    });
    traces.push({
      x: downs.map((e) => e.d),
      y: downs.map((e) => e.c),
      type: "scatter",
      mode: "markers",
      name: `-N% triggers (${downs.length})`,
      marker: { color: "#dc2626", size: 9, line: { color: "white", width: 1 } },
      hovertemplate:
        "-trigger<br>%{x|%b %d, %Y}<br>$%{y:.2f}<extra></extra>",
    });

    return traces;
  }

  function render(payload, thresholdPct, minStreak) {
    const events = detectEvents(payload.prices, thresholdPct);
    const ups = events.filter((e) => e.dir === "up").length;
    const downs = events.filter((e) => e.dir === "down").length;
    const streaks = findDownStreaks(events, minStreak);

    // Stats panel
    const statsEl = document.getElementById("sma-stats");
    const fmtDate = (d) =>
      new Date(d + "T00:00:00").toLocaleDateString(undefined, {
        year: "numeric", month: "short", day: "numeric",
      });
    statsEl.innerHTML = `
      <div class="sma-stat"><span class="lbl">Ticker</span><span class="val">${payload.ticker}</span></div>
      <div class="sma-stat"><span class="lbl">Range</span><span class="val">${fmtDate(payload.start)} → ${fmtDate(payload.end)}</span></div>
      <div class="sma-stat"><span class="lbl">Trading days</span><span class="val">${payload.prices.length.toLocaleString()}</span></div>
      <div class="sma-stat"><span class="lbl">+${thresholdPct}% triggers</span><span class="val up">${ups}</span></div>
      <div class="sma-stat"><span class="lbl">-${thresholdPct}% triggers</span><span class="val down">${downs}</span></div>
      <div class="sma-stat"><span class="lbl">Down-streaks (≥${minStreak})</span><span class="val">${streaks.length}</span></div>
    `;

    // Chart
    const traces = buildTraces(payload.prices, events);
    const layout = {
      title: {
        text: `${payload.ticker} — ±${thresholdPct}% moving-anchor events`,
        font: { size: 16 },
      },
      margin: { l: 60, r: 20, t: 60, b: 50 },
      hovermode: "closest",
      xaxis: { title: "Date", showgrid: true, gridcolor: "#e5e7eb" },
      yaxis: {
        title: "Adjusted close (USD)",
        showgrid: true,
        gridcolor: "#e5e7eb",
      },
      legend: { orientation: "h", y: -0.18 },
      plot_bgcolor: "white",
      paper_bgcolor: "white",
    };

    // Dark-mode detection (MkDocs Material toggle)
    const isDark =
      document.body.getAttribute("data-md-color-scheme") === "slate";
    if (isDark) {
      layout.plot_bgcolor = "#1e1e2e";
      layout.paper_bgcolor = "#1e1e2e";
      layout.font = { color: "#e5e7eb" };
      layout.xaxis.gridcolor = "#374151";
      layout.yaxis.gridcolor = "#374151";
    }

    Plotly.newPlot("sma-chart", traces, layout, {
      responsive: true,
      displaylogo: false,
    });

    // Streak table
    const tblEl = document.getElementById("sma-streaks");
    if (!streaks.length) {
      tblEl.innerHTML = `<p class="sma-empty">No down-streaks of ≥${minStreak} consecutive –${thresholdPct}% drops in this range.</p>`;
    } else {
      tblEl.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>#</th><th>Start</th><th>End</th><th>Triggers</th>
              <th>Duration</th><th>Drop</th>
            </tr>
          </thead>
          <tbody>
            ${streaks
              .map(
                (s, i) => `
              <tr>
                <td>${i + 1}</td>
                <td>${fmtDate(s.start_date)}<br><small>$${s.start_price.toFixed(2)}</small></td>
                <td>${fmtDate(s.end_date)}<br><small>$${s.end_price.toFixed(2)}</small></td>
                <td>${s.runs}</td>
                <td>${s.days} days</td>
                <td class="down">${s.drop_pct.toFixed(1)}%</td>
              </tr>`,
              )
              .join("")}
          </tbody>
        </table>
      `;
    }
  }

  // ---------- Wire up controls ----------
  async function init() {
    const chartEl = document.getElementById("sma-chart");
    if (!chartEl) return; // not on the chart page

    const tickerSelect = document.getElementById("sma-ticker");
    const thresholdInput = document.getElementById("sma-threshold");
    const thresholdLabel = document.getElementById("sma-threshold-label");
    const minStreakInput = document.getElementById("sma-minstreak");
    const minStreakLabel = document.getElementById("sma-minstreak-label");
    const updatedEl = document.getElementById("sma-updated");

    let manifest;
    try {
      manifest = await loadManifest();
    } catch (e) {
      chartEl.innerHTML = `<p class="sma-error">Could not load data manifest: ${e.message}</p>`;
      return;
    }

    // Populate dropdown
    tickerSelect.innerHTML = manifest.tickers
      .map((t) => `<option value="${t.ticker}">${t.ticker} — ${t.name}</option>`)
      .join("");

    updatedEl.textContent = `Data refreshed ${new Date(
      manifest.generated_at,
    ).toLocaleString()}`;

    async function update() {
      const ticker = tickerSelect.value;
      const threshold = parseFloat(thresholdInput.value);
      const minStreak = parseInt(minStreakInput.value, 10);
      thresholdLabel.textContent = `${threshold}%`;
      minStreakLabel.textContent = minStreak;

      try {
        const payload = await loadTicker(ticker);
        render(payload, threshold, minStreak);
      } catch (e) {
        chartEl.innerHTML = `<p class="sma-error">${e.message}</p>`;
      }
    }

    tickerSelect.addEventListener("change", update);
    thresholdInput.addEventListener("input", update);
    minStreakInput.addEventListener("input", update);

    // Re-render on Material's color-scheme toggle
    const observer = new MutationObserver(() => update());
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ["data-md-color-scheme"],
    });

    await update();
  }

  // MkDocs Material with navigation.instant re-fires document$ on nav.
  if (window.document$) {
    window.document$.subscribe(() => init());
  } else if (document.readyState !== "loading") {
    init();
  } else {
    document.addEventListener("DOMContentLoaded", init);
  }
})();
