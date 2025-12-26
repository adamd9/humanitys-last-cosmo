import { fetchJSON } from "../api.js";
import { state, loadModelSelection, notifyModelSelectionChanged, setCurrentStep } from "../state.js";

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

if (!customElements.get("model-picker")) {
  customElements.define("model-picker", ModelPicker);
}
