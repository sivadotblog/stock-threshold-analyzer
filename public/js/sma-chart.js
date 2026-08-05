/* SMA — Stock Moment Analysis
 *
 * Loads per-ticker JSON (raw daily closes) and renders an interactive
 * Plotly chart with a "moving-anchor +/-N% threshold" overlay. Threshold,
 * ticker, and date range are controlled by UI inputs and recomputed live
 * in the browser; no server round-trips after the initial JSON fetch.
 */

(function () {
  "use strict";

  function dataBase() {
    return window.__DATA_BASE__ || "/everest/data";
  }

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

  function findUpStreaks(events, minRun) {
    const rows = events.filter((e) => e.dir === "up" || e.dir === "down");
    const streaks = [];
    let i = 0;
    while (i < rows.length) {
      if (rows[i].dir === "up") {
        let j = i;
        while (j < rows.length && rows[j].dir === "up") j++;
        const runLen = j - i;
        if (runLen >= minRun) {
          const startEvt = i === 0 ? events[0] : rows[i - 1];
          const endEvt = rows[j - 1];
          const days =
            (Date.parse(endEvt.d) - Date.parse(startEvt.d)) /
            (1000 * 60 * 60 * 24);
          const gain = ((endEvt.c - startEvt.c) / startEvt.c) * 100;
          streaks.push({
            start_date: startEvt.d,
            start_price: startEvt.c,
            end_date: endEvt.d,
            end_price: endEvt.c,
            runs: runLen,
            days: Math.round(days),
            gain_pct: gain,
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

    const ups = events.filter((e) => e.dir === "up");
    const downs = events.filter((e) => e.dir === "down");
    traces.push({
      x: ups.map((e) => e.d),
      y: ups.map((e) => e.c),
      type: "scatter",
      mode: "markers",
      name: `+N% triggers (${ups.length})`,
      marker: { color: "#16a34a", size: 9, line: { color: "white", width: 1 } },
      hovertemplate: "+trigger<br>%{x|%b %d, %Y}<br>$%{y:.2f}<extra></extra>",
    });
    traces.push({
      x: downs.map((e) => e.d),
      y: downs.map((e) => e.c),
      type: "scatter",
      mode: "markers",
      name: `-N% triggers (${downs.length})`,
      marker: { color: "#dc2626", size: 9, line: { color: "white", width: 1 } },
      hovertemplate: "-trigger<br>%{x|%b %d, %Y}<br>$%{y:.2f}<extra></extra>",
    });

    return traces;
  }

  function render(payload, thresholdPct, minDownStreak, minUpStreak) {
    const events = detectEvents(payload.prices, thresholdPct);
    const ups = events.filter((e) => e.dir === "up").length;
    const downs = events.filter((e) => e.dir === "down").length;
    const downStreaks = findDownStreaks(events, minDownStreak);
    const upStreaks = findUpStreaks(events, minUpStreak);

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
      <div class="sma-stat"><span class="lbl">Up-streaks (≥${minUpStreak})</span><span class="val up">${upStreaks.length}</span></div>
      <div class="sma-stat"><span class="lbl">Down-streaks (≥${minDownStreak})</span><span class="val down">${downStreaks.length}</span></div>
    `;

    const traces = buildTraces(payload.prices, events);
    const cs = getComputedStyle(document.documentElement);
    const clrBg     = cs.getPropertyValue("--bg").trim()     || "#f7fafc";
    const clrBgCard = cs.getPropertyValue("--bg-card").trim()|| "#ffffff";
    const clrFg     = cs.getPropertyValue("--fg").trim()     || "#2d3748";
    const clrBorder = cs.getPropertyValue("--border").trim() || "#cbd5e0";
    const layout = {
      title: {
        text: `${payload.ticker} — ±${thresholdPct}% moving-anchor events`,
        font: { size: 16, color: clrFg },
      },
      margin: { l: 60, r: 20, t: 60, b: 50 },
      hovermode: "closest",
      xaxis: { title: "Date", showgrid: true, gridcolor: clrBorder, color: clrFg },
      yaxis: {
        title: "Adjusted close (USD)",
        showgrid: true,
        gridcolor: clrBorder,
        color: clrFg,
      },
      legend: { orientation: "h", y: -0.18, font: { color: clrFg } },
      plot_bgcolor: clrBgCard,
      paper_bgcolor: clrBg,
      font: { color: clrFg },
    };

    Plotly.newPlot("sma-chart", traces, layout, {
      responsive: true,
      displaylogo: false,
    });

    const upTblEl = document.getElementById("sma-up-streaks");
    if (!upStreaks.length) {
      upTblEl.innerHTML = `<p class="sma-empty">No up-streaks of ≥${minUpStreak} consecutive +${thresholdPct}% gains in this range.</p>`;
    } else {
      upTblEl.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>#</th><th>Start</th><th>End</th><th>Triggers</th>
              <th>Duration</th><th>Gain</th>
            </tr>
          </thead>
          <tbody>
            ${upStreaks
              .map(
                (s, i) => `
              <tr>
                <td>${i + 1}</td>
                <td>${fmtDate(s.start_date)}<br><small>$${s.start_price.toFixed(2)}</small></td>
                <td>${fmtDate(s.end_date)}<br><small>$${s.end_price.toFixed(2)}</small></td>
                <td>${s.runs}</td>
                <td>${s.days} days</td>
                <td class="up">+${s.gain_pct.toFixed(1)}%</td>
              </tr>`,
              )
              .join("")}
          </tbody>
        </table>
      `;
    }

    const downTblEl = document.getElementById("sma-streaks");
    if (!downStreaks.length) {
      downTblEl.innerHTML = `<p class="sma-empty">No down-streaks of ≥${minDownStreak} consecutive –${thresholdPct}% drops in this range.</p>`;
    } else {
      downTblEl.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>#</th><th>Start</th><th>End</th><th>Triggers</th>
              <th>Duration</th><th>Drop</th>
            </tr>
          </thead>
          <tbody>
            ${downStreaks
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
    if (!chartEl) return;

    const tickerSelect = document.getElementById("sma-ticker");
    const thresholdInput = document.getElementById("sma-threshold");
    const thresholdLabel = document.getElementById("sma-threshold-label");
    const minStreakInput = document.getElementById("sma-minstreak");
    const minStreakLabel = document.getElementById("sma-minstreak-label");
    const minUpStreakInput = document.getElementById("sma-minupstreak");
    const minUpStreakLabel = document.getElementById("sma-minupstreak-label");
    const updatedEl = document.getElementById("sma-updated");

    let manifest;
    try {
      manifest = await loadManifest();
    } catch (e) {
      chartEl.innerHTML = `<p class="sma-error">Could not load data manifest: ${e.message}</p>`;
      return;
    }

    tickerSelect.innerHTML = manifest.tickers
      .map((t) => `<option value="${t.ticker}">${t.ticker} — ${t.name}</option>`)
      .join("");

    // Deep link from the leaderboard: /chart/?ticker=XXXX preselects the row.
    const requested = new URLSearchParams(window.location.search)
      .get("ticker")?.toUpperCase();
    if (requested && manifest.tickers.some((t) => t.ticker === requested)) {
      tickerSelect.value = requested;
    }

    const filterInput = document.getElementById("sma-ticker-filter");
    if (filterInput) {
      filterInput.addEventListener("input", () => {
        const q = filterInput.value.toLowerCase();
        for (const opt of tickerSelect.options) {
          opt.hidden = !opt.text.toLowerCase().includes(q);
        }
        if (tickerSelect.selectedOptions[0]?.hidden) {
          const first = Array.from(tickerSelect.options).find((o) => !o.hidden);
          if (first) { tickerSelect.value = first.value; update(); }
        }
      });
    }

    updatedEl.textContent = `Data refreshed ${new Date(manifest.generated_at).toLocaleString()}`;

    async function update() {
      const ticker = tickerSelect.value;
      const threshold = parseFloat(thresholdInput.value);
      const minStreak = parseInt(minStreakInput.value, 10);
      const minUpStreak = parseInt(minUpStreakInput.value, 10);
      thresholdLabel.textContent = `${threshold}%`;
      minStreakLabel.textContent = minStreak;
      minUpStreakLabel.textContent = minUpStreak;

      const tvLink = document.getElementById("tv-link");
      if (tvLink && ticker) {
        tvLink.href = `https://www.tradingview.com/symbols/${encodeURIComponent(ticker)}/`;
        tvLink.textContent = `View ${ticker} on TradingView →`;
      }

      try {
        const payload = await loadTicker(ticker);
        render(payload, threshold, minStreak, minUpStreak);
      } catch (e) {
        chartEl.innerHTML = `<p class="sma-error">${e.message}</p>`;
      }
    }

    tickerSelect.addEventListener("change", update);
    thresholdInput.addEventListener("input", update);
    minStreakInput.addEventListener("input", update);
    minUpStreakInput.addEventListener("input", update);

    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => update());
    window.addEventListener("themechange", () => update());

    await update();
  }

  if (document.readyState !== "loading") {
    init();
  } else {
    document.addEventListener("DOMContentLoaded", init);
  }
})();
