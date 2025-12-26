import "./components/dashboard.js";
import "./components/chart-viewer.js";
import "./components/markdown-viewer.js";
import "./components/model-picker.js";
import "./components/quiz-library.js";
import "./components/quiz-uploader.js";
import "./components/run-creator.js";
import "./components/stepper-nav.js";
import { setCurrentStep, updateStepVisibility } from "./state.js";

updateStepVisibility();

document.querySelectorAll("[data-nav='dashboard']").forEach((btn) => {
  btn.addEventListener("click", () => setCurrentStep(0));
});
