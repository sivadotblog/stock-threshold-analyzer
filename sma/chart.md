# Interactive Chart

<div class="sma-controls">
  <div>
    <label for="sma-ticker">Ticker</label>
    <input id="sma-ticker-filter" type="text" placeholder="Search…"
           autocomplete="off" style="margin-bottom:4px;width:100%;display:block;" />
    <select id="sma-ticker"></select>
  </div>
  <div>
    <label for="sma-threshold">
      Threshold <span id="sma-threshold-label" class="value-pill">10%</span>
    </label>
    <input id="sma-threshold" type="range" min="1" max="25" step="0.5" value="10" />
  </div>
  <div>
    <label for="sma-minstreak">
      Min down-streak <span id="sma-minstreak-label" class="value-pill">3</span>
    </label>
    <input id="sma-minstreak" type="range" min="2" max="6" step="1" value="3" />
  </div>
</div>

<p id="sma-updated"></p>

<div id="sma-chart"></div>

## Summary

<div id="sma-stats"></div>

## Consecutive down-trigger streaks

<div id="sma-streaks"></div>
