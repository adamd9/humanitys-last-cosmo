import { fetchJSON, refreshRuns, selectRun } from "../api.js";
import { state, setCurrentStep } from "../state.js";
import { buildCapabilityRows, getEffectiveModelInfo, getQuizTypeLabel } from "../utils.js";

class RunCreator extends HTMLElement {
  connectedCallback() {
    this.render();
    document.addEventListener("quiz:updated", () => this.render());
    document.addEventListener("models:updated", () => this.render());
    document.addEventListener("runs:updated", () => this.render());
  }

  async createRun() {
    const status = this.querySelector(".status");
    const quizId = String(state.quiz?.id ?? "");
    if (!quizId) {
      status.textContent = "Load a quiz first.";
      return;
    }
    const group = state.selectedGroup || null;
    const checked = [...state.selectedModels];
    const payload = {
      quiz_id: quizId,
      models: checked.length ? checked : null,
      group: group || null,
      generate_report: true,
    };
    status.textContent = "Starting run...";
    try {
      const data = await fetchJSON("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      status.textContent = `Run created: ${data.run_id}. Opening dashboard...`;
      await refreshRuns();
      await selectRun(data.run_id);
      setCurrentStep(0);
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    }
  }

  render() {
    const compact = this.hasAttribute("data-compact");
    const quizTitle = state.quiz?.title || state.quiz?.id || "none";
    const modelInfo = getEffectiveModelInfo();
    const ruleTypes = state.quizMeta?.outcome_rule_types?.length
      ? state.quizMeta.outcome_rule_types.join(", ")
      : "none";
    const capabilityRows = buildCapabilityRows(state.quizMeta, modelInfo.count);
    const capabilities = state.quizMeta
      ? `
        <div class="status-grid">
          <div class="status">Quiz type: ${getQuizTypeLabel(state.quiz, state.quizMeta)}</div>
          <div class="status">Outcome rules: ${ruleTypes}</div>
          <div class="status">Outcomes: ${state.quizMeta.has_outcomes ? state.quizMeta.outcome_count : 0}</div>
          <div class="status">Choices: ${state.quizMeta.choice_count}</div>
          <div class="status">Model selection: ${modelInfo.label}</div>
        </div>
        <div class="asset-list columns">
          ${capabilityRows
            .map((row) => {
              const stateClass = row.ok ? "ready" : "missing";
              const stateLabel = row.ok ? "Included" : "Not included";
              const variants = row.variants?.length
                ? `<div class="status">Includes: ${row.variants.join(", ")}</div>`
                : "";
              return `
                <div class="asset-item ${stateClass}">
                  <span class="asset-status ${stateClass}" aria-hidden="true"></span>
                  <div class="asset-label">
                    <div class="asset-title">${row.label}</div>
                    ${variants}
                    <div class="status">${row.reason}</div>
                  </div>
                  <div class="asset-state">${stateLabel}</div>
                </div>
              `;
            })
            .join("")}
        </div>
      `
      : `<div class="status">Quiz details will appear after a quiz is loaded.</div>`;
    const actions = compact
      ? `
          <button id="runBtn">Run Quiz</button>
          <button class="secondary" data-setup>Update setup</button>
        `
      : `
          <button id="runBtn">Run Quiz</button>
          <button class="secondary" data-back>Back</button>
        `;
    this.innerHTML = `
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            <h2>${compact ? "Run Launchpad" : "Run Launchpad"}</h2>
            <div class="panel-subtitle">
              ${compact ? "Launch a run with the current setup." : "Choose a quiz, then launch."}
            </div>
          </div>
          ${compact ? "" : '<span class="badge">Step 4</span>'}
        </div>
        <div class="status-grid">
          <div class="status">${state.quiz ? `Quiz loaded: ${quizTitle}` : "No quiz loaded yet."}</div>
          <div class="status">
            Models: ${state.selectedModels.size || "none selected"}
            ${state.selectedGroup ? `(group: ${state.selectedGroup})` : ""}
          </div>
        </div>
        ${capabilities}
        <div class="actions">
          ${actions}
        </div>
        <div class="status">Results will appear in the runs list.</div>
      </div>
    `;
    this.querySelector("#runBtn").addEventListener("click", () => this.createRun());
    this.querySelector("button[data-back]")?.addEventListener("click", () => {
      setCurrentStep(3);
    });
    this.querySelector("button[data-setup]")?.addEventListener("click", () => {
      setCurrentStep(1);
    });
  }
}

if (!customElements.get("run-creator")) {
  customElements.define("run-creator", RunCreator);
}
