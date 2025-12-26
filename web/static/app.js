const state = {
  quiz: null,
  quizYaml: null,
  models: [],
  groups: {},
  runs: [],
  selectedRun: null,
  runResults: [],
  assets: [],
  runError: null,
};

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
      status.textContent = `Parsed quiz: ${state.quiz.id}`;
      this.render();
      document.dispatchEvent(new CustomEvent("quiz:updated"));
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    }
  }

  render() {
    const previewText = state.quizYaml || "";
    const quizMeta = state.quiz
      ? `
        <div class="status">Detected quiz type: ${getQuizType(state.quiz)}</div>
        <div class="status">Scoring: ${getScoringSummary(state.quiz)}</div>
      `
      : "";
    this.innerHTML = `
      <div class="panel">
        <h2>1) Convert Quiz</h2>
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
        </div>
        <div class="status">Waiting for input.</div>
        ${quizMeta}
        <pre class="preview">${previewText}</pre>
      </div>
    `;
  }
}

class ModelPicker extends HTMLElement {
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
    const modelList = state.models
      .map(
        (model) => `
        <label class="list-item">
          <input type="checkbox" value="${model.id}" ${model.available ? "" : "disabled"} />
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
        <h2>2) Pick Models</h2>
        <div>
          <label>Model group</label>
          <select id="groupSelect">
            <option value="">(none)</option>
            ${groupOptions}
          </select>
        </div>
        <div class="list">
          ${modelList}
        </div>
      </div>
    `;
  }
}

class RunCreator extends HTMLElement {
  connectedCallback() {
    this.render();
    document.addEventListener("quiz:updated", () => this.render());
    document.addEventListener("runs:updated", () => this.render());
  }

  async createRun() {
    const status = this.querySelector(".status");
    const quizId = state.quiz?.id;
    if (!quizId) {
      status.textContent = "Parse a quiz first.";
      return;
    }
    const group = document.querySelector("#groupSelect")?.value || null;
    const checked = [...document.querySelectorAll("model-picker input[type=checkbox]:checked")].map(
      (input) => input.value
    );
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
    this.innerHTML = `
      <div class="panel">
        <h2>3) Launch Run</h2>
        <div class="status">${state.quiz ? `Quiz loaded: ${state.quiz.id}` : "No quiz parsed yet."}</div>
        <div class="actions">
          <button id="runBtn">Run Quiz</button>
        </div>
        <div class="status">Results will appear in the runs list.</div>
      </div>
    `;
    this.querySelector("#runBtn").addEventListener("click", () => this.createRun());
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
        <h2>Runs</h2>
        <div class="status">${state.runError || ""}</div>
        <div class="list">${items || "<div class='status'>No runs yet.</div>"}</div>
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
        <h2>Results for ${state.selectedRun}</h2>
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
customElements.define("model-picker", ModelPicker);
customElements.define("run-creator", RunCreator);
customElements.define("run-list", RunList);
customElements.define("run-results", RunResults);

async function refreshRuns() {
  const data = await fetchJSON("/api/runs");
  state.runs = data.runs;
  document.dispatchEvent(new CustomEvent("runs:updated"));
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
