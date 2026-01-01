import "./components/dashboard.js";
import "./components/chart-viewer.js";
import "./components/markdown-viewer.js";
import "./components/model-picker.js";
import "./components/quiz-library.js";
import "./components/quiz-uploader.js";
import "./components/run-creator.js";
import "./components/stepper-nav.js";
import { selectRun } from "./api.js";
import { setCurrentStep, state } from "./state.js";

const stepRoutes = {
  0: "/",
  1: "/create-run",
  2: "/select-quiz",
  3: "/select-models",
  4: "/run-quiz",
};
const pathToStep = new Map(Object.entries(stepRoutes).map(([key, value]) => [value, Number(key)]));
let routerUpdating = false;
const runRoute = /^\/run\/([^/]+)$/;

function normalizePath(pathname) {
  if (!pathname || pathname === "/") return "/";
  return pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
}

function resolveRouteFromPath(pathname) {
  const normalized = normalizePath(pathname);
  const runMatch = normalized.match(runRoute);
  if (runMatch) {
    return { step: 0, runId: runMatch[1] };
  }
  return { step: pathToStep.get(normalized) ?? 0, runId: null };
}

function buildPathForState() {
  if (state.currentStep === 0 && state.selectedRun) {
    return `/run/${state.selectedRun}`;
  }
  return stepRoutes[state.currentStep] || "/";
}

function syncStepToUrl() {
  if (routerUpdating) return;
  const targetPath = buildPathForState();
  if (normalizePath(window.location.pathname) !== targetPath) {
    history.pushState({ step: state.currentStep }, "", targetPath);
  }
}

async function applyRoute(route) {
  routerUpdating = true;
  setCurrentStep(route.step);
  if (route.runId) {
    if (state.selectedRun !== route.runId) {
      try {
        await selectRun(route.runId);
      } catch (err) {
        state.runError = `Failed to load run: ${err.message}`;
      }
    }
  }
  routerUpdating = false;
}

window.addEventListener("popstate", () => {
  applyRoute(resolveRouteFromPath(window.location.pathname));
});

document.addEventListener("step:changed", syncStepToUrl);
document.addEventListener("run:selected", () => {
  if (state.currentStep !== 0) return;
  syncStepToUrl();
});

const initialRoute = resolveRouteFromPath(window.location.pathname);
applyRoute(initialRoute).then(() => {
  const initialPath = buildPathForState();
  if (normalizePath(window.location.pathname) !== initialPath) {
    history.replaceState({ step: initialRoute.step }, "", initialPath);
  }
});

document.querySelectorAll("[data-nav='dashboard']").forEach((btn) => {
  btn.addEventListener("click", () => setCurrentStep(0));
});
