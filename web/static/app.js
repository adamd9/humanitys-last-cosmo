const state = {
  quiz: null,
  quizYaml: null,
  quizRawPayload: null,
  quizRawPreview: null,
  quizMeta: null,
  quizzes: [],
  previewQuiz: null,
  previewQuizYaml: null,
  previewRawPayload: null,
  previewRawPreview: null,
  previewQuizMeta: null,
  models: [],
  groups: {},
  selectedModels: new Set(),
  selectedGroup: "",
  runs: [],
  selectedRun: null,
  selectedRunData: null,
  selectedRunQuizMeta: null,
  selectedRunQuizId: null,
  runResults: [],
  assets: [],
  runLog: "",
  runLogExists: false,
  runError: null,
  currentStep: 0,
};

const MODEL_SELECTION_KEY = "llm_pop_quiz_model_selection";

function loadModelSelection() {
  try {
    const raw = localStorage.getItem(MODEL_SELECTION_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed.models)) {
      state.selectedModels = new Set(parsed.models);
    }
    if (typeof parsed.group === "string") {
      state.selectedGroup = parsed.group;
    }
  } catch (err) {
    return;
  }
}

function saveModelSelection() {
  const payload = {
    models: [...state.selectedModels],
    group: state.selectedGroup || "",
  };
  try {
    localStorage.setItem(MODEL_SELECTION_KEY, JSON.stringify(payload));
  } catch (err) {
    return;
  }
}

function notifyModelSelectionChanged() {
  saveModelSelection();
  document.dispatchEvent(new CustomEvent("models:updated"));
}

async function fetchJSON(url, options) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || resp.statusText);
  }
  return resp.json();
}

function formatDate(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  return date.toLocaleString();
}

const ASSET_LABELS = {
  csv_raw_choices: "Raw choices CSV",
  csv_outcomes: "Outcome summary CSV",
  report_markdown: "Markdown report",
  chart_choices: "Choices chart",
  chart_comparison: "Choice comparison chart",
  chart_radar: "Choice radar chart",
  chart_heatmap: "Choice heatmap",
  chart_outcomes: "Outcome distribution chart",
  chart_model_outcomes: "Model-outcome matrix",
  chart_outcome_radar: "Outcome radar chart",
  chart_outcome_heatmap: "Outcome heatmap",
  chart_pandasai: "PandasAI chart",
};

function getAssetLabel(assetType) {
  return ASSET_LABELS[assetType] || assetType.replace(/_/g, " ");
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function buildExpectedAssetTypes(runData, quizMeta, assets) {
  const expected = [];
  const add = (type) => {
    if (!expected.includes(type)) {
      expected.push(type);
    }
  };
  add("report_markdown");
  add("csv_raw_choices");

  const modelCount = runData?.models?.length || 0;
  const hasOutcomes = quizMeta?.has_outcomes;
  const choiceCount = quizMeta?.choice_count || 0;

  if (hasOutcomes) {
    add("csv_outcomes");
    if (modelCount > 1) {
      add("chart_outcomes");
      add("chart_model_outcomes");
      add("chart_outcome_radar");
      add("chart_outcome_heatmap");
    } else {
      add("chart_choices");
    }
  } else if (modelCount > 1) {
    add("chart_comparison");
    if (choiceCount >= 3) {
      add("chart_radar");
    }
    if (choiceCount > 1) {
      add("chart_heatmap");
    }
  } else {
    add("chart_choices");
  }

  (assets || []).forEach((asset) => {
    if (asset.asset_type && asset.asset_type.startsWith("chart_")) {
      add(asset.asset_type);
    }
  });

  return expected;
}

class QuizUploader extends HTMLElement {
  connectedCallback() {
    this.render();
    this.querySelector("button").addEventListener("click", () => this.parseQuiz());
  }

  async parseQuiz() {
    const text = this.querySelector("textarea").value.trim();
    const fileInput = this.querySelector("input[type=file]");
    const status = this.querySelector(".status");
    status.textContent = "Parsing quiz...";

    try {
      let body;
      let headers = {};
      if (fileInput.files.length > 0) {
        body = new FormData();
        body.append("file", fileInput.files[0]);
      } else {
        body = new FormData();
        body.append("text", text);
      }
      const data = await fetchJSON("/api/quizzes/parse", { method: "POST", body, headers });
      state.quiz = data.quiz;
      state.quizYaml = data.quiz_yaml;
      state.quizRawPayload = data.raw_payload || null;
      state.quizRawPreview = data.raw_preview || null;
      state.quizMeta = data.quiz_meta || null;
      status.textContent = `Parsed quiz: ${state.quiz.id} (saved to library)`;
      this.render();
      await refreshQuizzes();
      document.dispatchEvent(new CustomEvent("quiz:updated"));
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    }
  }

  render() {
    const previewText =
      state.quizYaml ||
      (state.quiz ? "YAML preview is available after parsing a new quiz." : "");
    const quizMeta = state.quiz
      ? `
        <div class="status">Detected quiz type: ${getQuizTypeLabel(state.quiz, state.quizMeta)}</div>
        <div class="status">Scoring: ${getScoringSummary(state.quiz, state.quizMeta)}</div>
      `
      : "";
    this.innerHTML = `
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            <h2>Quiz Studio</h2>
            <div class="panel-subtitle">Convert a new quiz into YAML.</div>
          </div>
          <span class="badge">Step 1</span>
        </div>
        <div>
          <label>Paste quiz text</label>
          <textarea placeholder="Paste the quiz text here..."></textarea>
        </div>
        <div>
          <label>Or upload an image</label>
          <input type="file" accept="image/*" />
        </div>
        <div class="actions">
          <button>Parse to YAML</button>
          <button class="secondary" data-next>Next</button>
        </div>
        <div class="status">Waiting for input.</div>
        ${quizMeta}
        <pre class="preview">${previewText}</pre>
      </div>
    `;
    this.querySelector("button[data-next]")?.addEventListener("click", () => {
      setCurrentStep(2);
    });
  }
}

class QuizLibrary extends HTMLElement {
  constructor() {
    super();
    this.filterText = "";
  }

  connectedCallback() {
    this.render();
    refreshQuizzes();
    document.addEventListener("quizzes:updated", () => this.render());
    document.addEventListener("quiz:updated", () => this.render());
  }

  applyFilter(value) {
    this.filterText = value.toLowerCase();
    this.render();
  }

  async selectQuiz(quizId) {
    const status = this.querySelector(".status");
    status.textContent = "Loading quiz...";
    try {
      const data = await fetchJSON(`/api/quizzes/${quizId}`);
      state.quiz = data.quiz;
      state.quizYaml = data.quiz_yaml || null;
      state.quizRawPayload = data.raw_payload || null;
      state.quizRawPreview = data.raw_preview || null;
      state.quizMeta = data.quiz_meta || null;
      status.textContent = `Loaded quiz: ${quizId}`;
      document.dispatchEvent(new CustomEvent("quiz:updated"));
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    }
  }

  async previewQuiz(quizId) {
    const status = this.querySelector(".status");
    status.textContent = "Loading preview...";
    try {
      const data = await fetchJSON(`/api/quizzes/${quizId}`);
      state.previewQuiz = data.quiz;
      state.previewQuizYaml = data.quiz_yaml || null;
      state.previewRawPayload = data.raw_payload || null;
      state.previewRawPreview = data.raw_preview || null;
      state.previewQuizMeta = data.quiz_meta || null;
      status.textContent = `Previewing: ${quizId}`;
      this.render();
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    }
  }

  async reprocessQuiz(quizId) {
    const status = this.querySelector(".status");
    status.textContent = "Reprocessing quiz...";
    try {
      const body = new FormData();
      body.append("model", "gpt-4o");
      const data = await fetchJSON(`/api/quizzes/${quizId}/reprocess`, {
        method: "POST",
        body,
      });
      state.previewQuiz = data.quiz;
      state.previewQuizYaml = data.quiz_yaml || null;
      state.previewRawPayload = data.raw_payload || null;
      state.previewRawPreview = data.raw_preview || null;
      state.previewQuizMeta = data.quiz_meta || null;
      if (state.quiz?.id === quizId) {
        state.quiz = data.quiz;
        state.quizYaml = data.quiz_yaml || null;
        state.quizRawPayload = data.raw_payload || null;
        state.quizRawPreview = data.raw_preview || null;
        state.quizMeta = data.quiz_meta || null;
        document.dispatchEvent(new CustomEvent("quiz:updated"));
      }
      status.textContent = `Reprocessed: ${quizId}`;
      await refreshQuizzes();
      this.render();
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    }
  }

  async deleteQuiz(quizId) {
    const status = this.querySelector(".status");
    const confirmDelete = confirm(
      "Delete this quiz and any related runs? This action cannot be undone."
    );
    if (!confirmDelete) return;

    status.textContent = "Deleting quiz...";
    try {
      await fetchJSON(`/api/quizzes/${quizId}`, { method: "DELETE" });

      if (state.quiz?.id === quizId) {
        state.quiz = null;
        state.quizYaml = null;
        state.quizRawPayload = null;
        state.quizRawPreview = null;
        state.quizMeta = null;
      }

      if (state.previewQuiz?.id === quizId) {
        state.previewQuiz = null;
        state.previewQuizYaml = null;
        state.previewRawPayload = null;
        state.previewRawPreview = null;
        state.previewQuizMeta = null;
      }

      status.textContent = `Deleted quiz: ${quizId}`;
      await refreshQuizzes();
      document.dispatchEvent(new CustomEvent("quiz:updated"));
      this.render();
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    }
  }

  render() {
    const filter = this.filterText;
    const quizzes = state.quizzes.filter((quiz) => {
      if (!filter) return true;
      const haystack = `${quiz.quiz_id} ${quiz.title || ""}`.toLowerCase();
      return haystack.includes(filter);
    });
    const items = quizzes
      .map((quiz) => {
        const isActive = state.quiz?.id === quiz.quiz_id;
        const rawBadge = quiz.raw_available ? '<span class="tag">raw stored</span>' : "";
        return `
        <div class="list-item">
          <div>
            <strong>${quiz.title || quiz.quiz_id}</strong>
            <div class="status">ID: ${quiz.quiz_id} ${rawBadge}</div>
            <div class="status">Source: ${quiz.source?.source || "unknown"}</div>
          </div>
          <div class="actions">
            <button class="secondary" data-preview="${quiz.quiz_id}">View</button>
            <button class="secondary" data-quiz="${quiz.quiz_id}">
              ${isActive ? "Selected" : "Use this quiz"}
            </button>
            <button class="danger" data-delete="${quiz.quiz_id}">Delete</button>
          </div>
        </div>
      `;
      })
      .join("");
    const preview = state.previewQuiz
      ? `
        <div class="quiz-preview">
          <div class="panel-header">
            <div class="panel-title">
              <h3>${state.previewQuiz.title || state.previewQuiz.id}</h3>
              <div class="panel-subtitle">Quiz preview</div>
            </div>
            <div class="actions">
              ${state.previewRawPayload ? `<button class="secondary" data-reprocess="${state.previewQuiz.id}">Reprocess from raw</button>` : ""}
              <button class="secondary" data-clear-preview>Clear</button>
            </div>
          </div>
          ${renderQuizPreview(state.previewQuiz, {
            quizYaml: state.previewQuizYaml,
            rawPayload: state.previewRawPayload,
            rawPreview: state.previewRawPreview,
            quizMeta: state.previewQuizMeta,
          })}
        </div>
      `
      : "";
    this.innerHTML = `
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            <h2>Quiz Library</h2>
            <div class="panel-subtitle">Reuse saved quizzes for new runs.</div>
          </div>
          <span class="badge">Step 2</span>
        </div>
        <div class="toolbar">
          <input type="text" placeholder="Search quizzes..." value="${this.filterText}" />
        </div>
        <div class="list scroll">
          ${items || "<div class='status'>No saved quizzes yet.</div>"}
        </div>
        ${preview}
        <div class="status">Active quiz: ${state.quiz?.id || "none"}</div>
        <div class="actions">
          <button class="secondary" data-next>Next</button>
        </div>
      </div>
    `;
    this.querySelector("input[type=text]")?.addEventListener("input", (event) => {
      this.applyFilter(event.target.value);
    });
    this.querySelectorAll("button[data-quiz]").forEach((btn) => {
      btn.addEventListener("click", () => this.selectQuiz(btn.dataset.quiz));
    });
    this.querySelectorAll("button[data-preview]").forEach((btn) => {
      btn.addEventListener("click", () => this.previewQuiz(btn.dataset.preview));
    });
    this.querySelectorAll("button[data-delete]").forEach((btn) => {
      btn.addEventListener("click", () => this.deleteQuiz(btn.dataset.delete));
    });
    this.querySelectorAll("button[data-reprocess]").forEach((btn) => {
      btn.addEventListener("click", () => this.reprocessQuiz(btn.dataset.reprocess));
    });
    this.querySelector("button[data-clear-preview]")?.addEventListener("click", () => {
      state.previewQuiz = null;
      state.previewQuizYaml = null;
      state.previewRawPayload = null;
      state.previewRawPreview = null;
      state.previewQuizMeta = null;
      this.render();
    });
    this.querySelector("button[data-next]")?.addEventListener("click", () => {
      setCurrentStep(3);
    });
  }
}

class ModelPicker extends HTMLElement {
  constructor() {
    super();
    this.filterText = "";
    this.showAvailableOnly = false;
  }

  connectedCallback() {
    loadModelSelection();
    this.load();
  }

  async load() {
    const data = await fetchJSON("/api/models");
    state.models = data.models;
    state.groups = data.groups;
    const knownIds = new Set(state.models.map((model) => model.id));
    state.selectedModels = new Set(
      [...state.selectedModels].filter((id) => knownIds.has(id))
    );
    if (state.selectedGroup && !state.groups[state.selectedGroup]) {
      state.selectedGroup = "";
    }
    this.render();
  }

  render() {
    const groupOptions = Object.keys(state.groups)
      .map((group) => `<option value="${group}">${group}</option>`)
      .join("");
    const selectedIds = [...state.selectedModels];
    this.innerHTML = `
      <div class="model-picker-grid">
        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              <h2>Model Console</h2>
              <div class="panel-subtitle">Pick a group or cherry-pick models.</div>
            </div>
            <span class="badge">Step 3</span>
          </div>
          <div>
            <label>Model group</label>
            <select id="groupSelect">
              <option value="">(none)</option>
              ${groupOptions}
            </select>
          </div>
          <div class="toolbar">
            <input type="text" placeholder="Filter models..." value="${this.filterText}" />
            <label class="tag">
              <input type="checkbox" ${this.showAvailableOnly ? "checked" : ""} />
              available only
            </label>
          </div>
          <div class="actions">
            <button class="secondary" data-action="select-visible">Select visible</button>
            <button class="secondary" data-action="clear">Clear selection</button>
            <button data-next>Next</button>
          </div>
          <div class="list scroll list-grid" data-model-list></div>
          <div class="hint">Tip: filter to a short list, then select visible.</div>
        </div>
        <div class="panel selection-panel">
          <div class="panel-header">
            <div class="panel-title">
              <h2>Selected models</h2>
              <div class="panel-subtitle">Review your picks before running.</div>
            </div>
            <span class="badge">${selectedIds.length}</span>
          </div>
          <div class="selection-count"></div>
          <ul class="selection-list"></ul>
        </div>
      </div>
    `;
    this.updateModelList();
    this.updateSelectionSummary();
    const groupSelect = this.querySelector("#groupSelect");
    if (groupSelect) {
      groupSelect.value = state.selectedGroup || "";
      groupSelect.addEventListener("change", (event) => {
        state.selectedGroup = event.target.value;
        notifyModelSelectionChanged();
      });
    }
    this.querySelector("input[type=text]")?.addEventListener("input", (event) => {
      this.filterText = event.target.value.toLowerCase();
      this.updateModelList();
    });
    const availableToggle = this.querySelector(".toolbar input[type=checkbox]");
    if (availableToggle) {
      availableToggle.addEventListener("change", (event) => {
        this.showAvailableOnly = event.target.checked;
        this.updateModelList();
      });
    }
    this.querySelectorAll("button[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.dataset.action === "clear") {
          state.selectedModels.clear();
        }
        if (btn.dataset.action === "select-visible") {
          this.getFilteredModels().forEach((model) => {
            if (model.available) {
              state.selectedModels.add(model.id);
            }
          });
        }
        notifyModelSelectionChanged();
        this.updateSelectionSummary();
        this.updateModelList();
      });
    });
    this.querySelector("button[data-next]")?.addEventListener("click", () => {
      setCurrentStep(4);
    });
  }

  getFilteredModels() {
    return state.models.filter((model) => {
      if (this.showAvailableOnly && !model.available) return false;
      if (!this.filterText) return true;
      const haystack = `${model.name || ""} ${model.id} ${model.description || ""}`.toLowerCase();
      return haystack.includes(this.filterText);
    });
  }

  updateModelList() {
    const list = this.querySelector("[data-model-list]");
    if (!list) return;
    const filteredModels = this.getFilteredModels();
    list.innerHTML = filteredModels
      .map((model) => {
        const completionPrice = Number(model.pricing?.completion);
        const priceLabel = Number.isFinite(completionPrice)
          ? `$${(completionPrice * 1_000_000).toFixed(2)} / 1M`
          : "n/a";
        return `
        <label class="list-item model-card">
          <input
            type="checkbox"
            value="${model.id}"
            ${model.available ? "" : "disabled"}
            ${state.selectedModels.has(model.id) ? "checked" : ""}
          />
          <div class="model-meta">
            <strong class="model-title">${model.name || model.id}</strong>
            <div class="model-id">${model.id}</div>
            <div class="model-desc">${model.description || "No description"}</div>
            <span class="tag">${priceLabel}</span>
          </div>
        </label>
      `;
      })
      .join("");
    this.querySelectorAll("[data-model-list] input[type=checkbox][value]").forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) {
          state.selectedModels.add(input.value);
        } else {
          state.selectedModels.delete(input.value);
        }
        notifyModelSelectionChanged();
        this.updateSelectionSummary();
      });
    });
  }

  updateSelectionSummary() {
    const selectionCount = this.querySelector(".selection-count");
    const selectionList = this.querySelector(".selection-list");
    const selectionBadge = this.querySelector(".selection-panel .badge");
    if (!selectionCount || !selectionList || !selectionBadge) return;

    const modelLookup = new Map(state.models.map((model) => [model.id, model]));
    const selectedIds = [...state.selectedModels];
    selectionBadge.textContent = String(selectedIds.length);
    selectionCount.textContent = selectedIds.length
      ? `${selectedIds.length} selected`
      : "None selected";
    selectionList.innerHTML = selectedIds.length
      ? selectedIds
          .map((id) => {
            const model = modelLookup.get(id);
            const label = model?.name || id;
            const showId = model?.name && model.name !== id;
            return `
              <li class="selection-item">
                <div class="selection-name">${label}</div>
                ${showId ? `<div class="selection-id">${id}</div>` : ""}
              </li>
            `;
          })
          .join("")
      : `<li class="selection-empty">No models selected yet.</li>`;
  }
}

class RunCreator extends HTMLElement {
  connectedCallback() {
    this.render();
    document.addEventListener("quiz:updated", () => this.render());
    document.addEventListener("models:updated", () => this.render());
    document.addEventListener("runs:updated", () => this.render());
  }

  async createRun() {
    const status = this.querySelector(".status");
    const quizId = state.quiz?.id;
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
        <div class="status">Quiz type: ${getQuizTypeLabel(state.quiz, state.quizMeta)}</div>
        <div class="status">Outcome rules: ${ruleTypes}</div>
        <div class="status">Outcomes: ${state.quizMeta.has_outcomes ? state.quizMeta.outcome_count : 0}</div>
        <div class="status">Choices: ${state.quizMeta.choice_count}</div>
        <div class="status">Model selection: ${modelInfo.label}</div>
        <div class="list">
          ${capabilityRows
            .map(
              (row) => `
              <div class="list-item">
                <strong>${row.label}</strong>
                <div class="status">${row.ok ? "Applies" : "Not applicable"}: ${row.reason}</div>
              </div>
            `
            )
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
        <div class="status">${state.quiz ? `Quiz loaded: ${quizTitle}` : "No quiz loaded yet."}</div>
        <div class="status">
          Models: ${state.selectedModels.size || "none selected"}
          ${state.selectedGroup ? `(group: ${state.selectedGroup})` : ""}
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

class RunList extends HTMLElement {
  connectedCallback() {
    this.render();
    refreshRuns();
    document.addEventListener("runs:updated", () => this.render());
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
    const assetMap = new Map((state.assets || []).map((asset) => [asset.asset_type, asset]));
    const status = runData?.status || "unknown";
    const isActive = status && !["completed", "failed"].includes(status);
    const assetRows = expectedAssets
      .map((type) => {
        const asset = assetMap.get(type);
        const stateClass = asset ? "ready" : isActive ? "pending" : "missing";
        const stateLabel = asset ? "Ready" : isActive ? "Generating" : "Missing";
        const label = getAssetLabel(type);
        const link = asset?.url
          ? `<a href="${asset.url}" target="_blank" rel="noopener">${label}</a>`
          : `<span>${label}</span>`;
        return `
          <div class="asset-item ${stateClass}">
            <span class="asset-status ${stateClass}" aria-hidden="true"></span>
            <div class="asset-label">${link}</div>
            <div class="asset-state">${stateLabel}</div>
          </div>
        `;
      })
      .join("");
    const rows = state.runResults
      .slice(0, 20)
      .map(
        (row) => `
        <tr>
          <td>${row.model_id}</td>
          <td>${row.question_id}</td>
          <td>${row.choice}</td>
          <td>${row.refused ? "yes" : "no"}</td>
        </tr>
      `
      )
      .join("");
    const logBody = state.runLogExists
      ? state.runLog || "Log is still streaming..."
      : "Run log not available yet.";
    this.innerHTML = `
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            <h2>Results for ${state.selectedRun}</h2>
            <div class="panel-subtitle">Top 20 rows shown here.</div>
          </div>
        </div>
        <div class="status">${state.runError || ""}</div>
        <div class="status">
          Status:
          <span class="status-pill status-${status}">${status}</span>
          ${runData?.quiz_id ? `· Quiz: ${runData.quiz_id}` : ""}
        </div>
        <div class="asset-list">
          ${assetRows || "<div class='status'>No assets yet.</div>"}
        </div>
        <details class="run-log" ${isActive ? "open" : ""}>
          <summary>Run log (live)</summary>
          <pre class="run-log-body">${escapeHtml(logBody)}</pre>
        </details>
        <table class="table">
          <thead>
            <tr>
              <th>Model</th>
              <th>Question</th>
              <th>Choice</th>
              <th>Refused</th>
            </tr>
          </thead>
          <tbody>
            ${rows || "<tr><td colspan='4'>No results yet.</td></tr>"}
          </tbody>
        </table>
      </div>
    `;
  }
}

customElements.define("quiz-uploader", QuizUploader);
customElements.define("quiz-library", QuizLibrary);
customElements.define("model-picker", ModelPicker);
customElements.define("run-creator", RunCreator);
customElements.define("run-list", RunList);
customElements.define("run-results", RunResults);

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

customElements.define("run-dashboard", RunDashboard);

class StepperNav extends HTMLElement {
  connectedCallback() {
    this.render();
    document.addEventListener("step:changed", () => this.render());
  }

  render() {
    const steps = [
      { id: 1, label: "Convert quiz" },
      { id: 2, label: "Choose quiz" },
      { id: 3, label: "Pick models" },
      { id: 4, label: "Run quiz" },
    ];
    const buttons = steps
      .map(
        (step) => `
        <button class="${state.currentStep === step.id ? "active" : ""}" data-step="${step.id}">
          ${step.id}. ${step.label}
        </button>
      `
      )
      .join("");
    this.innerHTML = `
      <div class="stepper">
        <div class="stepper-nav">${buttons}</div>
        <div class="step-hint">Follow the steps left to right. Your current stage is highlighted.</div>
      </div>
    `;
    this.querySelectorAll("button[data-step]").forEach((btn) => {
      btn.addEventListener("click", () => setCurrentStep(Number(btn.dataset.step)));
    });
  }
}

customElements.define("stepper-nav", StepperNav);

async function refreshRuns() {
  const data = await fetchJSON("/api/runs");
  state.runs = data.runs;
  document.dispatchEvent(new CustomEvent("runs:updated"));
}

async function refreshQuizzes() {
  const data = await fetchJSON("/api/quizzes");
  state.quizzes = data.quizzes || [];
  document.dispatchEvent(new CustomEvent("quizzes:updated"));
}

async function loadRunDetails(runId, includeLog = false) {
  const requests = [
    fetchJSON(`/api/runs/${runId}`),
    fetchJSON(`/api/runs/${runId}/results`),
  ];
  if (includeLog) {
    requests.push(fetchJSON(`/api/runs/${runId}/log?tail=300`));
  }
  const [runData, resultsData, logData] = await Promise.all(requests);
  state.selectedRun = runId;
  state.selectedRunData = runData.run || null;
  state.assets = runData.assets || [];
  state.runResults = resultsData.results || [];
  state.runError = null;
  if (logData) {
    state.runLog = logData.log || "";
    state.runLogExists = Boolean(logData.exists);
  }
  if (!state.selectedRunQuizMeta || state.selectedRunQuizId !== runData.run.quiz_id) {
    try {
      const quizData = await fetchJSON(`/api/quizzes/${runData.run.quiz_id}`);
      state.selectedRunQuizMeta = quizData.quiz_meta || null;
      state.selectedRunQuizId = runData.run.quiz_id;
    } catch (err) {
      state.selectedRunQuizMeta = null;
      state.selectedRunQuizId = null;
    }
  }
}

async function selectRun(runId) {
  await loadRunDetails(runId, true);
  document.dispatchEvent(new CustomEvent("run:selected"));
}

function getQuizType(quiz) {
  const outcomes = quiz.outcomes || [];
  for (const outcome of outcomes) {
    const cond = outcome.condition || {};
    if (cond.mostlyTag) return "Tag-based";
    if (cond.scoreRange) return "Score-based";
    if (cond.mostly) return "Mostly letter";
  }
  const options = (quiz.questions || []).flatMap((q) => q.options || []);
  if (options.some((opt) => opt.tags && opt.tags.length)) return "Tag-based";
  if (options.some((opt) => typeof opt.score === "number")) return "Score-based";
  return "Mostly letter";
}

function getQuizTypeLabel(quiz, quizMeta) {
  if (quizMeta?.quiz_type) {
    return quizMeta.quiz_type;
  }
  return getQuizType(quiz);
}

function getScoringSummary(quiz, quizMeta) {
  const outcomes = quiz.outcomes || [];
  const mostly = outcomes
    .filter((o) => o.condition && o.condition.mostly)
    .map((o) => `${o.condition.mostly} -> ${o.text || o.id}`);
  if (mostly.length) {
    return mostly.join(", ");
  }
  const tag = outcomes
    .filter((o) => o.condition && o.condition.mostlyTag)
    .map((o) => `${o.condition.mostlyTag} -> ${o.text || o.id}`);
  if (tag.length) {
    return tag.join(", ");
  }
  const score = outcomes
    .filter((o) => o.condition && o.condition.scoreRange)
    .map((o) => {
      const range = o.condition.scoreRange;
      return `${range.min}-${range.max} -> ${o.text || o.id}`;
    });
  if (score.length) {
    return score.join(", ");
  }
  return "No explicit outcomes; defaulting to mostly-letter.";
}

function getEffectiveModelInfo() {
  if (state.selectedModels.size) {
    return {
      count: state.selectedModels.size,
      label: `${state.selectedModels.size} selected`,
    };
  }
  if (state.selectedGroup && state.groups[state.selectedGroup]) {
    const groupIds = state.groups[state.selectedGroup] || [];
    return {
      count: groupIds.length,
      label: `${state.selectedGroup} (${groupIds.length})`,
    };
  }
  const available = state.models.filter((model) => model.available);
  return {
    count: available.length,
    label: `all available (${available.length})`,
  };
}

function buildCapabilityRows(quizMeta, modelCount) {
  if (!quizMeta) return [];
  const hasOutcomes = quizMeta.has_outcomes;
  const outcomeCount = quizMeta.outcome_count || 0;
  const choiceCount = quizMeta.choice_count || 0;
  const isSingle = modelCount === 1;
  const isMulti = modelCount > 1;

  const rows = [];
  rows.push({
    label: "Outcome CSV",
    ok: hasOutcomes,
    reason: hasOutcomes
      ? "Created because outcomes are defined and report generation is enabled."
      : "Not created because the quiz has no outcomes.",
  });
  rows.push({
    label: "Choices bar chart (single model)",
    ok: isSingle,
    reason: isSingle
      ? "Generated for single-model runs."
      : "Only generated for single-model runs.",
  });
  rows.push({
    label: "Choice comparison bar chart",
    ok: isMulti && !hasOutcomes,
    reason: !isMulti
      ? "Requires multiple models."
      : hasOutcomes
        ? "Outcome-based quiz uses outcome charts instead."
        : "Generated for multi-model, non-outcome quizzes.",
  });
  rows.push({
    label: "Choice radar chart",
    ok: isMulti && !hasOutcomes && choiceCount >= 3,
    reason: !isMulti
      ? "Requires multiple models."
      : hasOutcomes
        ? "Outcome-based quiz uses outcome charts instead."
        : choiceCount < 3
          ? "Requires at least 3 choices."
          : "Generated for multi-model, non-outcome quizzes.",
  });
  rows.push({
    label: "Choice heatmap",
    ok: isMulti && !hasOutcomes && choiceCount > 1,
    reason: !isMulti
      ? "Requires multiple models."
      : hasOutcomes
        ? "Outcome-based quiz uses outcome charts instead."
        : choiceCount <= 1
          ? "Requires more than 1 choice."
          : "Generated for multi-model, non-outcome quizzes.",
  });
  rows.push({
    label: "Outcomes bar chart",
    ok: isMulti && hasOutcomes,
    reason: !isMulti
      ? "Requires multiple models."
      : hasOutcomes
        ? "Generated for multi-model outcome quizzes."
        : "Requires outcomes in the quiz YAML.",
  });
  rows.push({
    label: "Model to outcome matrix",
    ok: isMulti && hasOutcomes,
    reason: !isMulti
      ? "Requires multiple models."
      : hasOutcomes
        ? "Generated for multi-model outcome quizzes."
        : "Requires outcomes in the quiz YAML.",
  });
  rows.push({
    label: "Outcome radar chart",
    ok: isMulti && hasOutcomes && outcomeCount >= 3,
    reason: !isMulti
      ? "Requires multiple models."
      : !hasOutcomes
        ? "Requires outcomes in the quiz YAML."
        : outcomeCount < 3
          ? "Requires at least 3 outcomes."
          : "Generated for multi-model outcome quizzes.",
  });
  rows.push({
    label: "Outcome heatmap",
    ok: isMulti && hasOutcomes && outcomeCount > 1,
    reason: !isMulti
      ? "Requires multiple models."
      : !hasOutcomes
        ? "Requires outcomes in the quiz YAML."
        : outcomeCount <= 1
          ? "Requires more than 1 outcome."
          : "Generated for multi-model outcome quizzes.",
  });
  return rows;
}

function setCurrentStep(step) {
  state.currentStep = step;
  updateStepVisibility();
  document.dispatchEvent(new CustomEvent("step:changed"));
}

function updateStepVisibility() {
  document.querySelectorAll(".step-panel").forEach((panel) => {
    const panelStep = Number(panel.dataset.step);
    panel.classList.toggle("active", panelStep === state.currentStep);
  });
  const stepper = document.querySelector("stepper-nav");
  if (stepper) {
    stepper.style.display = state.currentStep === 0 ? "none" : "";
  }
}

updateStepVisibility();
document.querySelectorAll("[data-nav='dashboard']").forEach((btn) => {
  btn.addEventListener("click", () => setCurrentStep(0));
});

const outcomeConditionLabels = {
  mostly: "Mostly",
  mostlyTag: "Mostly tag",
  scoreRange: "Score range",
  score: "Score",
  tags: "Tags",
  tag: "Tag",
};

function formatOutcomeCondition(outcome = {}) {
  const entries = [];
  const condition = outcome.condition && typeof outcome.condition === "object" ? outcome.condition : null;
  if (condition) {
    entries.push(...formatConditionEntries(condition));
  }
  const directKeys = ["mostly", "mostlyTag", "scoreRange", "score", "tags", "tag"];
  directKeys.forEach((key) => {
    if (outcome[key] !== undefined) {
      entries.push(`${outcomeConditionLabels[key] || key}: ${formatConditionValue(outcome[key])}`);
    }
  });
  const uniqueEntries = [...new Set(entries)];
  return uniqueEntries.length ? uniqueEntries.join(" · ") : "Always";
}

function formatConditionEntries(condition = {}) {
  return Object.entries(condition).map(([key, value]) => {
    const label = outcomeConditionLabels[key] || key;
    return `${label}: ${formatConditionValue(value)}`;
  });
}

function formatConditionValue(value) {
  if (value && typeof value === "object") {
    if (typeof value.min === "number" && typeof value.max === "number") {
      return `${value.min}-${value.max}`;
    }
    return JSON.stringify(value);
  }
  return String(value);
}

function formatOptionDetails(option = {}) {
  const details = [];
  if (Array.isArray(option.tags) && option.tags.length) {
    details.push(`tags: ${option.tags.join(", ")}`);
  }
  if (typeof option.score === "number") {
    details.push(`score: ${option.score}`);
  }
  return details.length ? ` <span class="status">(${details.join(" · ")})</span>` : "";
}

function renderRawInput(rawPreview) {
  if (!rawPreview) {
    return "<div class=\"status\">Raw input not available.</div>";
  }
  if (rawPreview.type === "text") {
    return `<pre class="preview">${rawPreview.text || ""}</pre>`;
  }
  if (rawPreview.type === "image" && rawPreview.data_url) {
    return `
      <div class="raw-image-frame">
        <img src="${rawPreview.data_url}" alt="Uploaded quiz image" />
        <div class="status">${rawPreview.filename || "Uploaded image"} (${rawPreview.mime || ""})</div>
      </div>
    `;
  }
  return "<div class=\"status\">Raw input not available.</div>";
}

function renderQuizPreview(
  quiz,
  { quizYaml = null, rawPayload = null, rawPreview = null, quizMeta = null } = {}
) {
  const questions = quiz.questions || [];
  const items = questions
    .map((question, index) => {
      const qid = question.id || `q${index + 1}`;
      const options = (question.options || [])
        .map(
          (opt) =>
            `<li><strong>${opt.id || ""}</strong> ${opt.text || ""}${formatOptionDetails(opt)}</li>`
        )
        .join("");
      return `
        <div class="preview-item">
          <div class="status"><strong>${qid}.</strong> ${question.text || ""}</div>
          <ul>${options || "<li class='status'>No options listed.</li>"}</ul>
        </div>
      `;
    })
    .join("");

  const outcomes = (quiz.outcomes || [])
    .map((outcome) => {
      const title = outcome.id || outcome.text || outcome.description || "Outcome";
      const description = outcome.description || outcome.text || outcome.result || "";
      return `
        <li>
          <strong>${title}</strong>
          <div class="status">${formatOutcomeCondition(outcome)}</div>
          <div>${description}</div>
        </li>
      `;
    })
    .join("");

  const yamlBlock = quizYaml
    ? `
      <details class="yaml-preview">
        <summary>View YAML</summary>
        <pre class="preview">${quizYaml}</pre>
      </details>
    `
    : "";

  const rawBlock = rawPayload
    ? `
      <details class="raw-preview">
        <summary>View raw ${rawPreview?.type === "image" ? "image" : "text"}</summary>
        ${renderRawInput(rawPreview)}
      </details>
    `
    : "";

  const metaRows = [
    ["Quiz ID", quiz.id || ""],
    ["Type", getQuizTypeLabel(quiz, quizMeta)],
    ["Scoring", getScoringSummary(quiz, quizMeta)],
    ["Notes", quiz.notes || "—"],
    ["Raw backup", rawPayload ? `${rawPayload.type || "stored"}` : "Not stored"],
  ]
    .map(
      ([label, value]) => `
        <div>
          <div class="label">${label}</div>
          <div>${value || "—"}</div>
        </div>
      `
    )
    .join("");

  return `
    <div class="meta-grid">${metaRows}</div>
    <div class="preview-subsection">
      <h4>Questions (${questions.length || 0})</h4>
      <div class="preview-list">${items || "<div class='status'>No questions.</div>"}</div>
    </div>
    <div class="preview-subsection">
      <h4>Outcomes & scoring</h4>
      <ul class="outcome-list">${outcomes || "<li class='status'>No outcomes defined.</li>"}</ul>
    </div>
    ${rawBlock}
    ${yamlBlock}
  `;
}
