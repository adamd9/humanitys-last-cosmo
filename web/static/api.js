import { state } from "./state.js";

export async function fetchJSON(url, options) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || resp.statusText);
  }
  return resp.json();
}

export async function refreshRuns() {
  const data = await fetchJSON("/api/runs");
  state.runs = data.runs;
  document.dispatchEvent(new CustomEvent("runs:updated"));
}

export async function refreshQuizzes() {
  const data = await fetchJSON("/api/quizzes");
  state.quizzes = data.quizzes || [];
  document.dispatchEvent(new CustomEvent("quizzes:updated"));
  const quizIds = new Set(state.quizzes.map((quiz) => quiz.quiz_id));
  const hasActiveQuiz = state.quiz?.id && quizIds.has(state.quiz.id);
  if (!hasActiveQuiz && state.quizzes.length > 0) {
    await loadQuiz(state.quizzes[0].quiz_id);
    document.dispatchEvent(new CustomEvent("quiz:updated"));
  }
}

export async function loadQuiz(quizId) {
  const data = await fetchJSON(`/api/quizzes/${quizId}`);
  state.quiz = data.quiz;
  state.quizYaml = data.quiz_yaml || null;
  state.quizRawPayload = data.raw_payload || null;
  state.quizRawPreview = data.raw_preview || null;
  state.quizMeta = data.quiz_meta || null;
  return data;
}

export async function loadRunDetails(runId, includeLog = false) {
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

export async function selectRun(runId) {
  await loadRunDetails(runId, true);
  document.dispatchEvent(new CustomEvent("run:selected"));
}
