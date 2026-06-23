# Autonomous Research Reports

This page displays the latest findings from the Autonomous Machine Learning Agent.

<div id="report-container" class="report-card">
  <em>Loading latest agent report...</em>
</div>

<script>
// Material for MkDocs uses `navigation.instant` (AJAX page loads), so a plain
// DOMContentLoaded listener never fires on navigation. Subscribe to Material's
// `document$` observable, which emits on every page load (initial + instant nav).
// Fall back to a one-shot run if `document$` is unavailable.
function renderResearchReport() {
    const container = document.getElementById("report-container");
    if (!container) return; // not on the reports page

    // The page is served at ".../reports/", so we must go up one level to reach
    // the site-root "data/" directory. A bare relative path would 404.
    fetch("../data/research_report.json", { cache: "no-store" })
    .then(response => {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
    })
    .then(data => {
        const date = new Date(data.generated_at).toLocaleString();

        // Escape HTML to prevent basic XSS from agent output
        const escapeHTML = str => String(str).replace(/[&<>'"]/g,
            tag => ({
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                "'": '&#39;',
                '"': '&quot;'
            }[tag]));

        const analysisHTML = escapeHTML(data.analysis);

        container.innerHTML = `
            <h2>Prompt</h2>
            <blockquote>${escapeHTML(data.query)}</blockquote>
            <p><small>Generated at: ${date}</small></p>
            <hr/>
            <h3>Agent Analysis</h3>
            <div style="white-space: pre-wrap; font-size: 0.9em; background: var(--md-code-bg-color); padding: 15px; border-radius: 8px;">${analysisHTML}</div>
        `;
    })
    .catch(error => {
        container.textContent = "";
        const p = document.createElement("p");
        p.style.color = "red";
        p.textContent = "Error loading report or no report generated yet (" + error + "). Run `python research_agent.py` to generate one.";
        container.appendChild(p);
    });
}

if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(renderResearchReport);
} else {
    document.addEventListener("DOMContentLoaded", renderResearchReport);
}
</script>

<style>
.report-card {
    padding: 20px;
    border: 1px solid var(--md-default-fg-color--lightest);
    border-radius: 10px;
    margin-top: 20px;
    background-color: var(--md-default-bg-color);
    box-shadow: 0 4px 6px rgba(0,0,0,0.05);
}
.report-card h2 {
    margin-top: 0;
    color: var(--md-primary-fg-color);
}
</style>
