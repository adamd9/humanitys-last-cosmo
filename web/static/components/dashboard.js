import { loadRunDetails, refreshRuns, rerunReport, selectRun } from "../api.js";
import { state, setCurrentStep } from "../state.js";
import { buildAssetGroups, buildExpectedAssetTypes, escapeHtml, formatDate } from "../utils.js";

class RunList extends HTMLElement {
  connectedCallback() {
    this.render();
    refreshRuns();
    document.addEventListener("runs:updated", () => this.render());
    document.addEventListener("run:selected", () => this.render());
  }

  render() {
    const items = state.runs
      .map(
        (run) => `
        <div class="list-item ${state.selectedRun === run.run_id ? "active" : ""}" data-run="${run.run_id}">
          <strong>${run.run_id}</strong>
          <div class="status">Quiz: ${run.quiz_id}</div>
          <div class="status">
            Status: <span class="status-pill status-${run.status}">${run.status}</span>
          </div>
          <div class="status">${formatDate(run.created_at)}</div>
        </div>
      `
      )
      .join("");
    this.innerHTML = `
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            <h2>Quiz runs</h2>
          </div>
          <div class="actions">
            <button data-new-run>New run</button>
          </div>
        </div>
        <div class="status">${state.runError || ""}</div>
        <div class="list scroll">${items || "<div class='status'>No runs yet.</div>"}</div>
      </div>
    `;
    this.querySelector("button[data-new-run]")?.addEventListener("click", () => {
      setCurrentStep(1);
    });
    this.querySelectorAll(".list-item[data-run]").forEach((item) => {
      item.addEventListener("click", async () => {
        const runId = item.dataset.run;
        try {
          state.runError = null;
          await selectRun(runId);
          this.render();
        } catch (err) {
          state.runError = `Failed to load run: ${err.message}`;
          this.render();
        }
      });
    });
  }
}

class RunLog extends HTMLElement {
  connectedCallback() {
    this.render();
  }

  render() {
    const runData = state.selectedRunData;
    const status = runData?.status || "unknown";
    const isActive = status && !["completed", "failed"].includes(status);
    const logBody = state.runLogExists
      ? state.runLog || "Log is still streaming..."
      : "Run log not available yet.";
    this.innerHTML = `
      <details class="run-log" ${isActive ? "open" : ""}>
        <summary>Run log (live)</summary>
        <pre class="run-log-body">${escapeHtml(logBody)}</pre>
      </details>
    `;
  }
}

class RunPanel extends HTMLElement {
  connectedCallback() {
    this.render();
  }

  render() {
    if (!state.selectedRun) {
      this.innerHTML = `
        <div class="panel">
          <h2>Results</h2>
          <div class="status">Select a run to view results.</div>
        </div>
      `;
      return;
    }
    const runData = state.selectedRunData;
    const expectedAssets = buildExpectedAssetTypes(runData, state.selectedRunQuizMeta, state.assets);
    const assetGroups = buildAssetGroups(expectedAssets, state.assets || []);
    const status = runData?.status || "unknown";
    const isActive = status && !["completed", "failed"].includes(status);
    const hasResults = (state.runResults || []).length > 0;
    const canRerun = !isActive && hasResults;
    const rerunDisabled = state.reanalysisInProgress || !canRerun;
    const rerunLabel = state.reanalysisInProgress ? "Re-running analysis..." : "Re-run analysis";
    const assetRows = assetGroups
      .map((group) => {
        const asset = group.primaryAsset;
        const stateClass = group.readyCount > 0 ? "ready" : isActive ? "pending" : "missing";
        const stateLabel = group.readyCount > 0 ? "Ready" : isActive ? "Generating" : "Missing";
        const rawPath = asset?.path || "";
        const fileName = rawPath.split(/[/\\]/).pop() || "report.md";
        const lowerPath = rawPath.toLowerCase();
        const isMarkdown =
          Boolean(asset) &&
          (asset.asset_type === "report_markdown" ||
            lowerPath.endsWith(".md") ||
            lowerPath.endsWith(".markdown"));
        const isChart =
          Boolean(asset) &&
          (asset.asset_type?.startsWith("chart_") ||
            lowerPath.endsWith(".png") ||
            lowerPath.endsWith(".jpg") ||
            lowerPath.endsWith(".jpeg") ||
            lowerPath.endsWith(".gif") ||
            lowerPath.endsWith(".webp") ||
            lowerPath.endsWith(".svg"));
        const link = asset?.url
          ? isMarkdown
            ? `<button class="asset-link" data-markdown-url="${escapeHtml(asset.url)}" data-markdown-title="${escapeHtml(
                group.label
              )}" data-markdown-filename="${escapeHtml(fileName)}">${group.label}</button>`
            : isChart
              ? `<button class="asset-link" data-chart-url="${escapeHtml(asset.url)}" data-chart-title="${escapeHtml(
                  group.label
                )}" data-chart-filename="${escapeHtml(fileName)}">${group.label}</button>`
              : `<a href="${asset.url}" target="_blank" rel="noopener">${group.label}</a>`
          : `<span>${group.label}</span>`;
        const variants =
          group.variants?.length > 1
            ? `<div class="status">Includes: ${group.variants.join(", ")}</div>`
            : "";
        return `
          <div class="asset-item ${stateClass}">
            <span class="asset-status ${stateClass}" aria-hidden="true"></span>
            <div class="asset-label">
              <div class="asset-title">${link}</div>
              ${variants}
            </div>
            <div class="asset-state">${stateLabel}</div>
          </div>
        `;
      })
      .join("");
    const modelCount = runData?.models?.length || 0;
    const modelList = modelCount
      ? runData.models.map((model) => escapeHtml(model)).join(", ")
      : "No models recorded.";
    const groupLabel = runData?.settings?.group
      ? escapeHtml(runData.settings.group)
      : "";
    this.innerHTML = `
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            <h2>Results for ${state.selectedRun}</h2>
          </div>
          <div class="actions">
            <button class="secondary" data-rerun-report ${rerunDisabled ? "disabled" : ""}>${rerunLabel}</button>
          </div>
        </div>
        <div class="status-grid">
          <div class="status status-wrap">Models (${modelCount}): ${modelList}</div>
          ${groupLabel ? `<div class="status">Group: ${groupLabel}</div>` : ""}
          ${state.runError ? `<div class="status">${state.runError}</div>` : ""}
          <div class="status">
            Status:
            <span class="status-pill status-${status}">${status}</span>
            ${runData?.quiz_id ? `· Quiz: ${runData.quiz_id}` : ""}
          </div>
        </div>
        <div class="asset-list">
          ${assetRows || "<div class='status'>No assets yet.</div>"}
        </div>
        <run-log></run-log>
      </div>
    `;
    this.querySelector("button[data-rerun-report]")?.addEventListener("click", async () => {
      if (rerunDisabled) return;
      state.reanalysisInProgress = true;
      state.runError = null;
      this.render();
      try {
        await rerunReport(state.selectedRun);
        await refreshRuns();
        await selectRun(state.selectedRun);
      } catch (err) {
        state.runError = `Failed to re-run analysis: ${err.message}`;
      } finally {
        state.reanalysisInProgress = false;
        this.render();
      }
    });
    this.querySelectorAll("button[data-markdown-url]").forEach((button) => {
      button.addEventListener("click", () => {
        document.dispatchEvent(
          new CustomEvent("markdown:open", {
            detail: {
              url: button.dataset.markdownUrl,
              title: button.dataset.markdownTitle,
              filename: button.dataset.markdownFilename,
            },
          })
        );
      });
    });
    this.querySelectorAll("button[data-chart-url]").forEach((button) => {
      button.addEventListener("click", () => {
        document.dispatchEvent(
          new CustomEvent("chart:open", {
            detail: {
              url: button.dataset.chartUrl,
              title: button.dataset.chartTitle,
              filename: button.dataset.chartFilename,
            },
          })
        );
      });
    });
  }
}

class RunResults extends HTMLElement {
  connectedCallback() {
    this.pollId = null;
    document.addEventListener("run:selected", () => this.startPolling());
    this.render();
  }

  disconnectedCallback() {
    this.stopPolling();
  }

  stopPolling() {
    if (this.pollId) {
      clearInterval(this.pollId);
      this.pollId = null;
    }
  }

  async startPolling() {
    this.stopPolling();
    await this.refresh();
    if (state.selectedRun) {
      this.pollId = setInterval(() => this.refresh(), 4000);
    }
  }

  async refresh() {
    if (!state.selectedRun) {
      this.render();
      return;
    }
    try {
      await loadRunDetails(state.selectedRun, true);
    } catch (err) {
      state.runError = `Failed to refresh run: ${err.message}`;
    }
    this.render();
    const status = state.selectedRunData?.status || "";
    if (status && ["completed", "failed"].includes(status)) {
      this.stopPolling();
    }
  }

  render() {
    this.innerHTML = `<run-panel></run-panel>`;
  }
}

class RunDashboard extends HTMLElement {
  connectedCallback() {
    this.render();
  }

  render() {
    this.innerHTML = `
      <div class="dashboard-grid">
        <div class="dashboard-column">
          <run-list></run-list>
        </div>
        <div class="dashboard-column">
          <run-results></run-results>
        </div>
      </div>
    `;
  }
}

if (!customElements.get("run-list")) {
  customElements.define("run-list", RunList);
}
if (!customElements.get("run-log")) {
  customElements.define("run-log", RunLog);
}
if (!customElements.get("run-panel")) {
  customElements.define("run-panel", RunPanel);
}
if (!customElements.get("run-results")) {
  customElements.define("run-results", RunResults);
}
if (!customElements.get("run-dashboard")) {
  customElements.define("run-dashboard", RunDashboard);
}
