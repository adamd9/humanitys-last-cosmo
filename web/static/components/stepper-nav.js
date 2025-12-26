import { state, setCurrentStep } from "../state.js";

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

if (!customElements.get("stepper-nav")) {
  customElements.define("stepper-nav", StepperNav);
}
