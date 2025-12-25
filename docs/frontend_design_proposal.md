# LLM Pop Quiz Bench: Front-End Design Proposal

This document has two parts:
1) A clear explanation of how the current codebase works end-to-end.
2) A design proposal for a full front-end that starts from uploading/capturing a quiz photo and ends with results, charts, and reports.

The goal is to keep this understandable for a reasonably technical reader without requiring deep engineering context.

---

## 1) How the Current Codebase Works (Plain-English Overview)

### What the system does today
The project runs magazine-style quizzes against multiple LLMs, collects answers, scores outcomes, and produces Markdown/CSV reports with optional charts.

### Main pieces and how they connect
1) **CLI entry point** (`llm_pop_quiz_bench/cli/main.py`)
   - Provides commands like:
     - `benchmark`: run a quiz + generate report immediately.
     - `quiz:run`: run the quiz only.
     - `quiz:report`: generate a report from existing results.
     - `quiz:convert`: convert raw text to quiz YAML using OpenAI.
   - Builds a list of adapters (models) and passes them into the runner.

2) **Model configuration** (`config/models.yaml`, `llm_pop_quiz_bench/core/model_config.py`)
   - Defines available models, API key env vars, and default parameters.
   - `ModelConfigLoader` reads the config and creates adapters based on selection.
   - Supports model groups (e.g., `default`, `openai_comparison`).

3) **Adapters (LLM providers)** (`llm_pop_quiz_bench/adapters/*.py`)
   - Each adapter knows how to call its provider (OpenAI, Anthropic, Google, Grok).
   - Adapters expose a shared `send()` method and return:
     - `text` (model response)
     - token counts (if available)
     - latency
   - There is also a `MockAdapter` for tests or offline runs.

4) **Prompt builder** (`llm_pop_quiz_bench/core/prompt.py`)
   - Converts each question into a strict JSON-response prompt.
   - Supports any number of answer choices (A, B, C, D, ...).

5) **Runner** (`llm_pop_quiz_bench/core/runner.py`)
   - Loads the quiz YAML file.
   - For each model and each question:
     - Builds prompt
     - Calls adapter
     - Parses JSON response (`core/utils.py`)
     - Records the result with timing and tokens
   - Writes results as JSON to `results/<run_dir>/raw/<quiz_id>.json`.

6) **Scoring and reporting** (`llm_pop_quiz_bench/core/reporter.py`, `llm_pop_quiz_bench/core/llm_scorer.py`)
   - `reporter.py` loads results and builds:
     - CSVs
     - Markdown report (outcomes table, choices per question, charts)
   - `llm_scorer.py` can:
     - Score outcomes using an OpenAI model (if key is present)
     - Fall back to simple "mostly letter" scoring
   - Charts are generated with matplotlib; optional PandasAI charts exist in `core/visualizer.py`.

7) **Quiz conversion** (`llm_pop_quiz_bench/core/quiz_converter.py`)
   - Uses OpenAI to turn raw text into structured quiz YAML.
   - This is useful if you already have the quiz text.

### Where output lives
Runs are stored in timestamped directories under:
- `results/` or `results_mock/`
  - `raw/` -> JSON per quiz
  - `summary/` -> CSV + Markdown report
  - `charts/` -> PNG charts

### Current limitations
There is no web UI. Everything is driven by CLI and local files.
There is no OCR or image ingestion. Quizzes must exist as YAML or text.

---

## 2) Front-End Design Proposal

### Big idea
Build a simple web app that guides a user from **quiz image upload/camera capture -> quiz extraction -> quiz configuration -> run -> results**, using the existing Python logic as a backend engine.

The UI should feel like a short wizard, not a complicated dashboard.

---

## 2.1 User Journey (End-to-End)

1) **Upload / Capture / Paste Text**
   - User uploads a photo, PDF, or screenshots of a quiz.
   - Mobile users can use camera capture directly.
   - Alternative: paste raw quiz text into a text box.

2) **Extract + Parse (Image or Text)**
   - If image/PDF: backend runs OCR to extract text.
   - If text: skip OCR and use the provided text directly.
   - The text is converted to a quiz YAML structure via LLM.
   - UI shows a preview with light editing (title, questions, choices).

3) **Quiz Type + Scoring**
   - The system proposes a quiz type:
     - Mostly letter (A/B/C/D)
     - Tag-based
     - Score-based
   - If the quiz does not fit these types, the UI should block the run and ask the user to adjust the quiz or re-parse.
   - User can override or adjust scoring rules within the supported types.
   - Optional: "Auto-detect scoring" via LLM.

4) **Model Selection**
   - Show models from `config/models.yaml`.
   - Select group or custom list.

5) **Diagram / Report Settings**
   - Choose chart types (bar, radar, heatmap, outcomes).
   - Toggle LLM-generated summary.

6) **Run & Monitor**
   - Click Run.
   - Progress screen shows status by model and question.
   - Errors surface clearly (bad API keys, model unavailable).

7) **Results**
   - Outcomes table
   - Per-question choices
   - Charts
   - Markdown + CSV download

---

## 2.2 Proposed UI (Screens)

1) **Landing / Start**
  - "Start new quiz run"
  - "View past runs"

2) **Step 1: Upload, Capture, or Paste Text**
   - File drop zone + camera capture button + text input
   - Preview thumbnails

3) **Step 2: OCR/Text + Quiz Preview**
   - Show extracted or pasted text
   - Parsed quiz preview with editable fields
  - "Looks good" confirmation

4) **Step 3: Scoring Configuration**
   - Quiz type suggestion with confidence
   - Inline editor for outcomes/rules

5) **Step 4: Models + Parameters**
   - List of available models
   - Group picker (from `model_groups`)
   - Basic params (temperature, max_tokens) if needed

6) **Step 5: Chart + Report Settings**
   - Choose chart types
   - Toggle LLM summary
   - Output directory (optional)

7) **Step 6: Run Status**
   - Live log (model-by-model progress)
  - Errors shown with "Fix and retry"

8) **Results**
   - Rich report view
   - Download buttons (CSV, Markdown, images)

---

## 2.3 Backend Changes (API Layer)

The existing Python code can stay mostly the same. We add a lightweight API server that calls into it.

**Recommended stack:**
- FastAPI (Python)
- Background tasks (Celery/RQ or FastAPI background tasks)
- SQLite for run metadata (optional, can be JSON files initially)

### Key API Endpoints

- `POST /api/quizzes/import-image`
  - Uploads image/PDF, returns file ID

- `POST /api/quizzes/ocr`
  - Runs OCR, returns extracted text

- `POST /api/quizzes/parse`
  - Converts text -> quiz YAML (uses `quiz_converter.py`)
  - Accepts either OCR output or user-pasted text

- `POST /api/quizzes`
  - Saves quiz definition (YAML or JSON)

- `GET /api/models`
  - Returns available models and groups

- `POST /api/runs`
  - Starts a run (quiz + model list + settings)

- `GET /api/runs/{run_id}`
  - Status, progress, logs

- `GET /api/runs/{run_id}/results`
  - Summaries, CSV data, markdown

- `GET /api/runs/{run_id}/assets`
  - Charts, images

---

## 2.4 Quiz Identification & Scoring Logic

### Detection strategy
1) **Heuristic pass**
   - If outcomes include `mostly`, assume mostly-letter quiz.
   - If options include `tags`, assume tag-based.
   - If options include `score`, assume score-based.

2) **LLM-assisted pass**
   - If unclear, ask a small LLM to classify the quiz type and propose rules.
   - If it cannot map to a supported type, return an error and require user edits.

### User override
Always allow the user to correct the quiz type or scoring logic in the UI.

---

## 2.5 Diagram / Report Modes

Expose the existing report and chart outputs as selectable options:

- **Outcome charts** (if outcomes exist)
- **Choice distribution** (per model)
- **Radar chart** (choice profiles)
- **Heatmap** (model vs choice)

Add a simple checkbox UI to enable/disable each chart type, but lock the options by quiz type using the mapping below.

### Chart Type Mapping (by Quiz Type)

Supported quiz types:
- Mostly letter
- Tag-based
- Score-based

Chart availability:
- Mostly letter
  - Outcomes bar chart (outcome distribution)
  - Choice distribution (grouped bar)
  - Radar chart (choice profile)
  - Heatmap (model vs choice)
- Tag-based
  - Outcomes bar chart (tag-based outcome distribution)
  - Choice distribution (grouped bar)
  - Heatmap (model vs choice)
  - Radar chart (choice profile) only if tags map cleanly to a small, fixed set (otherwise hide)
- Score-based
  - Outcomes bar chart (score-based outcome distribution)
  - Choice distribution (grouped bar)
  - Heatmap (model vs choice)
  - Radar chart (choice profile) disabled (scores do not map to choice proportions)

UI behavior:
- The UI should only display chart toggles that are valid for the detected quiz type.
- If the quiz type changes, reset invalid chart selections.

---

## 2.6 Data and Storage

**Runtime data root**
- All temp and run data lives under a single runtime directory.
- The path is configurable via an environment variable (example: `LLM_POP_QUIZ_RUNTIME_DIR`).
- If unset, default to a sensible local path (example: `runtime-data/` in the project root).

**Separation of data types**
- **Raw run data + history:** stored in SQLite under the runtime directory.
- **Generated assets:** charts, Markdown reports, and CSV exports live in a separate assets subfolder under the runtime directory.
- **Uploads:** images/PDFs saved under an uploads subfolder under the runtime directory.

**SQLite schema (conceptual)**
- `runs`: run_id, quiz_id, created_at, status, models, settings
- `results`: run_id, model_id, question_id, choice, reason, latency_ms, tokens_in, tokens_out, refused
- `quizzes`: quiz_id, title, source, quiz_yaml
- `assets`: run_id, asset_type, path, created_at

This keeps raw data queryable and makes asset management explicit.

---

## 2.7 Security / API Keys

API keys must stay on the backend.
The UI should only show which models are available (based on keys present).
If a key is missing, show a friendly "Unavailable" state.

---

## 2.8 Phased Implementation Plan

### Phase 1: Backend data model + storage
- Introduce runtime data directory + env var configuration.
- Add SQLite storage for runs/results/quizzes/assets.
- Update reporter and runner outputs to store raw results in SQLite and write assets to the assets folder.

### Phase 2: Backend API scaffolding
- Add API endpoints for run metadata and results (`GET /api/runs`, `GET /api/runs/{id}`).
- Wire these endpoints to SQLite-backed queries.

### Phase 3: Frontend read-only UI
- Build UI that can list past runs + view results.

### Phase 4: "Upload -> Parse -> Save"
- Add OCR pipeline.
- Add quiz preview + editor.
- Persist quiz YAML.

### Phase 5: Full Run Flow
- Add run creation + live status.
- Show reports and charts directly in UI.

### Phase 6: UX polish
- Camera capture on mobile
- Better error recovery
- "Retry failed model only"

---

## 2.9 Open Questions to Decide Early

Answered:
1) Hosting target is a full service, but the first milestone should run locally with frontend + backend in the same repo and started together.
   - Frontend preference: frameworkless, no build step, standard HTML5 + Web Components.
2) OCR provider: use the existing converter model (GPT-4o) directly on images; no separate OCR vendor.
3) Editing: minimal; keep a lightweight preview + small edits only.

---

## 2.10 Why this design fits the current codebase

- The CLI runner and reporter already do most of the heavy lifting.
- The only major missing piece is an API layer plus OCR + quiz parsing workflow.
- A web UI can call the same internal functions:
  - `quiz_converter.text_to_yaml()`
  - `runner.run_quiz()`
  - `reporter.generate_markdown_report()`

This keeps the changes incremental and avoids rewriting core logic.

---

## 3) Summary in One Sentence
This proposal adds a simple web interface that wraps the existing CLI pipeline with OCR, quiz parsing, scoring selection, and results visualization, without changing the core engine.
