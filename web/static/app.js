const state = {
  quiz: null,
  quizYaml: null,
  quizRawPayload: null,
  quizRawPreview: null,
  quizzes: [],
  previewQuiz: null,
  previewQuizYaml: null,
  previewRawPayload: null,
  previewRawPreview: null,
  models: [],
  groups: {},
  selectedModels: new Set(),
  selectedGroup: "",
  runs: [],
  selectedRun: null,
  runResults: [],
  assets: [],
  runError: null,
  currentStep: 1,
};

function notifyModelSelectionChanged() {
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
        <div class="status">Detected quiz type: ${getQuizType(state.quiz)}</div>
        <div class="status">Scoring: ${getScoringSummary(state.quiz)}</div>
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
      if (state.quiz?.id === quizId) {
        state.quiz = data.quiz;
        state.quizYaml = data.quiz_yaml || null;
        state.quizRawPayload = data.raw_payload || null;
        state.quizRawPreview = data.raw_preview || null;
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
      }

      if (state.previewQuiz?.id === quizId) {
        state.previewQuiz = null;
        state.previewQuizYaml = null;
        state.previewRawPayload = null;
        state.previewRawPreview = null;
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
    this.load();
  }

  async load() {
    const data = await fetchJSON("/api/models");
    state.models = data.models;
    state.groups = data.groups;
    this.render();
  }

  render() {
    const groupOptions = Object.keys(state.groups)
      .map((group) => `<option value="${group}">${group}</option>`)
      .join("");
    const filteredModels = state.models.filter((model) => {
      if (this.showAvailableOnly && !model.available) return false;
      if (!this.filterText) return true;
      const haystack = `${model.id} ${model.description || ""}`.toLowerCase();
      return haystack.includes(this.filterText);
    });
    const modelList = filteredModels
      .map(
        (model) => `
        <label class="list-item">
          <input
            type="checkbox"
            value="${model.id}"
            ${model.available ? "" : "disabled"}
            ${state.selectedModels.has(model.id) ? "checked" : ""}
          />
          <div>
            <strong>${model.id}</strong>
            <div class="status">${model.description || "No description"}</div>
            <span class="tag">${model.available ? "available" : "unavailable"}</span>
          </div>
        </label>
      `
      )
      .join("");
    this.innerHTML = `
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
        <div class="list scroll list-grid">
          ${modelList}
        </div>
        <div class="hint">Tip: filter to a short list, then select visible.</div>
      </div>
    `;
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
      this.render();
    });
    const availableToggle = this.querySelector(".toolbar input[type=checkbox]");
    if (availableToggle) {
      availableToggle.addEventListener("change", (event) => {
        this.showAvailableOnly = event.target.checked;
        this.render();
      });
    }
    this.querySelectorAll("input[type=checkbox][value]").forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) {
          state.selectedModels.add(input.value);
        } else {
          state.selectedModels.delete(input.value);
        }
        notifyModelSelectionChanged();
        this.render();
      });
    });
    this.querySelectorAll("button[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.dataset.action === "clear") {
          state.selectedModels.clear();
        }
        if (btn.dataset.action === "select-visible") {
          filteredModels.forEach((model) => {
            if (model.available) {
              state.selectedModels.add(model.id);
            }
          });
        }
        notifyModelSelectionChanged();
        this.render();
      });
    });
    this.querySelector("button[data-next]")?.addEventListener("click", () => {
      setCurrentStep(4);
    });
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
      status.textContent = `Run created: ${data.run_id}`;
      await refreshRuns();
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    }
  }

  render() {
    const quizTitle = state.quiz?.title || state.quiz?.id || "none";
    this.innerHTML = `
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            <h2>Run Launchpad</h2>
            <div class="panel-subtitle">Choose a quiz, then launch.</div>
          </div>
          <span class="badge">Step 4</span>
        </div>
        <div class="status">${state.quiz ? `Quiz loaded: ${quizTitle}` : "No quiz loaded yet."}</div>
        <div class="status">
          Models: ${state.selectedModels.size || "none selected"}
          ${state.selectedGroup ? `(group: ${state.selectedGroup})` : ""}
        </div>
        <div class="actions">
          <button id="runBtn">Run Quiz</button>
          <button class="secondary" data-back>Back</button>
        </div>
        <div class="status">Results will appear in the runs list.</div>
      </div>
    `;
    this.querySelector("#runBtn").addEventListener("click", () => this.createRun());
    this.querySelector("button[data-back]")?.addEventListener("click", () => {
      setCurrentStep(3);
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
        <div class="list-item">
          <strong>${run.run_id}</strong>
          <div class="status">Quiz: ${run.quiz_id}</div>
          <div class="status">Status: ${run.status}</div>
          <div class="status">${formatDate(run.created_at)}</div>
          <button class="secondary" data-run="${run.run_id}">View</button>
        </div>
      `
      )
      .join("");
    this.innerHTML = `
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            <h2>Recent Runs</h2>
            <div class="panel-subtitle">Review previous executions.</div>
          </div>
          <span class="badge">${state.runs.length}</span>
        </div>
        <div class="status">${state.runError || ""}</div>
        <div class="list scroll">${items || "<div class='status'>No runs yet.</div>"}</div>
      </div>
    `;
    this.querySelectorAll("button[data-run]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const runId = btn.dataset.run;
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
    document.addEventListener("run:selected", () => this.render());
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
    const assets = state.assets
      .map((asset) => {
        if (asset.url) {
          return `<a href="${asset.url}" target="_blank">${asset.asset_type}</a>`;
        }
        return `<span>${asset.asset_type}</span>`;
      })
      .join(", ");
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
    this.innerHTML = `
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            <h2>Results for ${state.selectedRun}</h2>
            <div class="panel-subtitle">Top 20 rows shown here.</div>
          </div>
        </div>
        <div class="status">${state.runError || ""}</div>
        <div class="status">Assets: ${assets || "none"}</div>
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
      { id: 4, label: "Run + review" },
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

async function selectRun(runId) {
  const [runData, resultsData] = await Promise.all([
    fetchJSON(`/api/runs/${runId}`),
    fetchJSON(`/api/runs/${runId}/results`),
  ]);
  state.selectedRun = runId;
  state.assets = runData.assets || [];
  state.runResults = resultsData.results || [];
  state.runError = null;
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

function getScoringSummary(quiz) {
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
}

updateStepVisibility();

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

function renderQuizPreview(quiz, { quizYaml = null, rawPayload = null, rawPreview = null } = {}) {
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
    ["Type", getQuizType(quiz)],
    ["Scoring", getScoringSummary(quiz)],
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
