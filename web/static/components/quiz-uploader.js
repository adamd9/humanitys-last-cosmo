import { fetchJSON, refreshQuizzes } from "../api.js";
import { state, setCurrentStep } from "../state.js";
import { getQuizTypeLabel, getScoringSummary } from "../utils.js";

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

if (!customElements.get("quiz-uploader")) {
  customElements.define("quiz-uploader", QuizUploader);
}
