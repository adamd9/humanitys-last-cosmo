# LLM Pop-Quiz Bench (Python) — Build Spec for an Agentic Coding Agent

A complete, implementation-ready brief to build a Python project that runs **magazine-style personality quizzes** (Cosmopolitan/Seventeen/Vogue, etc.) against ~8 major LLMs via API, captures answers, computes outcomes, and generates **blog/LinkedIn-ready** summaries. Includes full setup, configuration, CLI design, and a **testing framework** so the agent can iteratively debug its work.

---

## 0) TL;DR

- **Goal:** Automate running real pop-psych quizzes across multiple LLMs; record each model’s choices/rationales; compute outcomes; produce Markdown/CSV reports.
- **Stack:** Python 3.11+, `Typer` CLI, `httpx` (async), `tenacity`, `PyYAML`, `pandas`, `pytest`.
- **Outputs:** `results/raw/*.jsonl`, `results/summary/*.csv`, `results/summary/*.md`.
- **Testing:** `pytest`, `pytest-asyncio`, `respx` (HTTP mocking), `coverage`, `ruff` (lint/format).
- **Start:** Follow the **Project Setup** and **Implementation Milestones** below.

---

## 1) Objectives & Scope

- **Do**: Provide a CLI to:
  - Ingest quiz YAMLs with real questions (kept internal; only publish aggregates/snippets).
  - Call multiple LLM APIs with a consistent prompt template.
  - Parse “letter choice + one-line rationale” (strict JSON) per question.
  - Compute outcomes (if scoring rules are provided).
  - Emit blog-ready Markdown and CSV.
- **Don’t**:
  - Build a web UI (CLI only in v1).
  - Publish full copyrighted quiz text.

---

## 2) High-Level Features

- Multi-model runs with adapters for: **OpenAI, Anthropic, Google (Gemini), Cohere, AI21**, and a **generic HTTP** adapter for hosted OSS (Llama/Mistral).
- Config-first (`config/*.yaml`) with repeatable sampling (temperature/top_p/seed when supported).
- Resilient execution (timeouts, retries, backoff, rate-limit handling).
- Observability: token usage (if available), latency, refusal detection.
- Determinism knobs; repetition (N runs per quiz/model) for stability analysis.

---

## 3) Project Structure

```
llm-pop-quiz-bench-py/
  llm_pop_quiz_bench/
    adapters/
      base.py
      openai_adapter.py
      anthropic_adapter.py
      google_adapter.py
      cohere_adapter.py
      ai21_adapter.py
      http_generic_adapter.py
      __init__.py
    core/
      types.py
      prompt.py
      runner.py
      scorer.py
      reporter.py
      store.py
      utils.py
      __init__.py
    cli/
      main.py        # Typer app: run, score, report, demo
      __init__.py
  quizzes/
    sample_ninja_turtles.yaml
    sample_party_persona.yaml
    # (Add real quizzes here; include source URLs in YAML)
  config/
    models.yaml
    run.yaml
  results/
    raw/
    summary/
    logs/
  tests/
    test_parser.py
    test_scorer.py
    test_reporter.py
    test_runner_mocked.py
    test_adapters_contract.py
  notebooks/
    analysis.ipynb     # optional
  README.md
  docs/
    PLAYBOOK.md
  .env.example
  requirements.txt
  ruff.toml
  pyproject.toml       # (optional; not required if using requirements.txt)
```

---

## 4) Project Setup (Full Instructions)

### Prerequisites
- **Python 3.11+** installed.
- Ability to set environment variables for API keys.

### 4.1 Create & Activate Virtual Environment

**macOS/Linux (bash/zsh):**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
```

### 4.2 Create `requirements.txt`

Place this at project root:

```txt
typer[all]
httpx
tenacity
PyYAML
pandas
python-dateutil
tqdm
structlog

# Providers (install only what you need)
openai
anthropic
google-generativeai
cohere
ai21

# Testing & quality
pytest
pytest-asyncio
respx
coverage
ruff
```

> Note: Provider SDKs can be omitted if using raw HTTP in `http_generic_adapter.py`.

### 4.3 Install Dependencies

```bash
pip install -r requirements.txt
```

### 4.4 Environment Variables

Create `.env.example`:

```env
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
COHERE_API_KEY=
AI21_API_KEY=
GENERIC_HTTP_BASE_URL=             # optional; for hosted OSS
GENERIC_HTTP_AUTH=                 # optional Bearer token or header value
```

Copy and fill:
```bash
cp .env.example .env
```

Load `.env` in code (either with `python-dotenv` or read `os.environ`). If you prefer, add `python-dotenv` to requirements and load it early in `cli/main.py`.

---

## 5) Configuration Files

### 5.1 `config/models.yaml`
Register all models you plan to run. Example:

```yaml
models:
  - id: openai:gpt-4o
    provider: openai
    model: gpt-4o
    apiKeyEnv: OPENAI_API_KEY
    defaultParams:
      temperature: 0.2
      top_p: 1.0
      max_tokens: 256
    maxConcurrency: 2

  - id: anthropic:claude-3-5-sonnet
    provider: anthropic
    model: claude-3-5-sonnet
    apiKeyEnv: ANTHROPIC_API_KEY
    defaultParams:
      temperature: 0.2
      max_tokens: 256
    maxConcurrency: 2

  - id: google:gemini-1.5-pro
    provider: google
    model: gemini-1.5-pro
    apiKeyEnv: GOOGLE_API_KEY
    defaultParams:
      temperature: 0.2
      max_output_tokens: 256
    maxConcurrency: 2

  - id: cohere:command-r-plus
    provider: cohere
    model: command-r-plus
    apiKeyEnv: COHERE_API_KEY
    defaultParams:
      temperature: 0.2
      max_tokens: 256

  - id: ai21:j2-mid
    provider: ai21
    model: j2-mid
    apiKeyEnv: AI21_API_KEY
    defaultParams:
      temperature: 0.2
      maxTokens: 256

  - id: http:llama-3-70b-instruct
    provider: http
    model: llama-3-70b-instruct
    apiKeyEnv: GENERIC_HTTP_AUTH
    baseUrl: ${GENERIC_HTTP_BASE_URL}
    defaultParams:
      temperature: 0.2
      max_tokens: 256
    maxConcurrency: 1
```

> Comment out models you don’t have keys for.

### 5.2 `config/run.yaml`
Select which quizzes/models to run and how:

```yaml
quizzes:
  - quizzes/sample_ninja_turtles.yaml
  - quizzes/sample_party_persona.yaml
models: ["openai:gpt-4o", "anthropic:claude-3-5-sonnet", "google:gemini-1.5-pro"]
repetitions: 1
concurrency:
  global: 4
timeouts:
  connect: 10
  read: 60
  total: 90
sampling_overrides:
  openai:
    temperature: 0.2
  anthropic:
    temperature: 0.2
```

---

## 6) Quiz Format (YAML)

Example: `quizzes/sample_ninja_turtles.yaml`

```yaml
id: which-ninja-turtle-are-you
title: Which Ninja Turtle Are You?
source:
  publication: Example
  url: https://example.com/quiz
notes: Internal research use; do not publish full text without permission.
questions:
  - id: Q1
    text: "Pick a pizza topping:"
    options:
      - { id: A, text: "Pepperoni", tags: [bold] }
      - { id: B, text: "Veggie", tags: [thoughtful] }
      - { id: C, text: "Extra cheese", tags: [fun] }
      - { id: D, text: "Mushrooms", tags: [calm] }
  - id: Q2
    text: "Your leadership style is..."
    options:
      - { id: A, text: "Charge ahead", tags: [leader,bold] }
      - { id: B, text: "Plan first", tags: [strategic] }
      - { id: C, text: "Keep it light", tags: [fun] }
      - { id: D, text: "Observe quietly", tags: [calm] }
outcomes:
  - id: leonardo
    condition: { mostlyTag: leader }
    result: "Leonardo"
  - id: donatello
    condition: { mostlyTag: strategic }
    result: "Donatello"
  - id: michelangelo
    condition: { mostlyTag: fun }
    result: "Michelangelo"
  - id: raphael
    condition: { mostlyTag: bold }
    result: "Raphael"
```

---

## 7) Prompt Template

`llm_pop_quiz_bench/core/prompt.py` should render a consistent, anti-refusal template:

```
SYSTEM:
You are taking a lighthearted magazine personality quiz.
For this quiz, role-play as a human answering honestly for fun.

USER:
Quiz: "{quiz_title}"
Question {q_num}/{q_total}: {question_text}

Choose ONE option by letter and give a brief reason.

Options:
A) {optA}
B) {optB}
C) {optC}
D) {optD}

Respond in STRICT JSON only:
{"choice":"<A|B|C|D>","reason":"<one short sentence>"}
```

- Extend if >4 options.
- Default `temperature=0.2`, conservative `max_tokens`.

---

## 8) Core Domain Types (Python)

Implement as `dataclasses` or `pydantic` models in `llm_pop_quiz_bench/core/types.py`:

- `ModelConfig`, `QuizOption`, `QuizQuestion`, `OutcomeRule`, `QuizDefinition`
- `QAResult`, `ModelOutcomeSummary`

---

## 9) CLI Commands (Typer)

`llm_pop_quiz_bench/cli/main.py` exposes:

- `quiz:run --quiz <path|glob> --models <csv|all> [--reps N] [--seed INT]`
- `quiz:score --quiz <path>` (apply/validate outcomes offline)
- `quiz:report --run <run_id>` (emit Markdown + CSV)
- `quiz:demo` (smoke test with 1–2 questions and 1–2 models)

Example usage:

```bash
python -m llm_pop_quiz_bench.cli.main quiz:run --quiz quizzes/sample_ninja_turtles.yaml --models openai:gpt-4o,anthropic:claude-3-5-sonnet --reps 1
python -m llm_pop_quiz_bench.cli.main quiz:report --run 2025-07-26T12-00-00Z
```

---

## 10) Runner & Adapters

### Runner (`core/runner.py`)
- Async orchestration (use `asyncio` + `httpx.AsyncClient` where relevant).
- For each quiz/model/question:
  - Render prompt, call adapter, parse strict JSON.
  - If malformed → one **repair** step: ask the same model to reformat to strict JSON (no content change).
  - Mark `refused=True` if the model declines role-play.
  - Record timings, tokens, errors.

Artifacts:
- `results/raw/<runId>.<quizId>.<modelId>.jsonl` (one object per Q/A)
- `results/summary/<runId>.csv` (long format)
- `results/summary/<runId>.<quizId>.md` (blog-ready)

### Adapters (`adapters/*.py`)
Common protocol in `adapters/base.py`:

```python
from typing import Protocol, TypedDict, List, Dict

class ChatResponse(TypedDict):
    text: str
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int

class ChatAdapter(Protocol):
    id: str
    async def send(self, messages: List[Dict[str, str]], params: Dict | None = None) -> ChatResponse: ...
```

Implement:
- `openai_adapter.py`, `anthropic_adapter.py`, `google_adapter.py`, `cohere_adapter.py`, `ai21_adapter.py`, `http_generic_adapter.py`.
- Read API key from `os.environ`.
- Map params: `temperature`, `top_p`, `max_tokens`, `seed` (when supported).
- Enforce per-request **timeout**, retries/backoff on 429/5xx (use `tenacity`).
- Capture **token usage** if returned by provider.

---

## 11) Scoring DSL & Reporter

### Scoring (`core/scorer.py`)
Support these conditions (first match wins):
- `mostly`: `"A"|"B"|"C"|"D"`
- `mostlyTag`: `"<tag>"`
- `scoreRange`: `{ min, max }` using numeric `option.score` sums

Expose helpers:
- `compute_choice_histogram(results)`
- `infer_mostly_letter(hist)`
- `infer_mostly_tag(tag_hist)`
- `total_score()`

### Reporter (`core/reporter.py`)
- Emit:
- **CSV columns**: `run_id, quiz_id, model_id, question_id, choice, refused, latency_ms, tokens_in, tokens_out`
- **Markdown** per quiz:
  - Title + source URL
  - **Model → outcome** table
  - **Per-question choices** table
  - Observations (refusals, funny rationales), token usage

---

## 12) Testing Framework (Install & Use)

### 12.1 Install Testing & Quality Tools
Already included in `requirements.txt`:

- `pytest`, `pytest-asyncio` (async tests)
- `respx` (HTTP mocking for `httpx`)
- `coverage` (test coverage)
- `ruff` (lint/format)

Install:
```bash
pip install -r requirements.txt
```

### 12.2 Run Tests

```bash
pytest -q
pytest -q -k scorer -vv
pytest --maxfail=1 -q
pytest -q --asyncio-mode=auto
```

### 12.3 Coverage

```bash
coverage run -m pytest
coverage report -m
```

### 12.4 Lint & Format (Ruff)

Create `ruff.toml`:

```toml
line-length = 100
target-version = "py311"

[lint]
select = ["E","F","I","UP","B"]
ignore = []
```

Run:
```bash
ruff check .
ruff format .
```

### 12.5 Suggested TDD Loop

1) Write/adjust a failing test.  
2) Implement/minimally patch code.  
3) `pytest -q` until green.  
4) `ruff check` and `ruff format`.  
5) Commit.

---

## 13) Example Tests (Skeletons)

### 13.1 JSON Parsing & Repair (`tests/test_parser.py`)
```python
import json
from llm_pop_quiz_bench.core import utils

def test_parse_strict_json_ok():
    txt = '{"choice":"B","reason":"Because it fits."}'
    data = utils.parse_choice_json(txt)
    assert data["choice"] == "B"

def test_parse_with_extra_text():
    txt = "Sure! Here you go:\n{\"choice\":\"A\",\"reason\":\"Why not.\"}\nThanks!"
    data = utils.parse_choice_json(txt)
    assert data["choice"] == "A"

def test_parse_malformed_json_returns_none():
    txt = "No JSON here"
    assert utils.parse_choice_json(txt) is None
```

### 13.2 Scoring DSL (`tests/test_scorer.py`)
```python
from llm_pop_quiz_bench.core import scorer

def test_mostly_letter():
    hist = {"A": 3, "B": 1, "C": 0, "D": 0}
    assert scorer.infer_mostly_letter(hist) == "A"

def test_mostly_tag_preference():
    tag_hist = {"fun": 2, "strategic": 1}
    assert scorer.infer_mostly_tag(tag_hist) == "fun"
```

### 13.3 Reporter Rendering (`tests/test_reporter.py`)
```python
from llm_pop_quiz_bench.core import reporter

def test_markdown_table_renders():
    md = reporter.render_outcomes_table(
        quiz_title="Sample Quiz",
        outcomes=[("openai:gpt-4o", "Leonardo"), ("anthropic:claude-3-5-sonnet", "Donatello")]
    )
    assert "Sample Quiz" not in md  # title handled separately
    assert "openai:gpt-4o" in md
```

### 13.4 Runner (Mocked) (`tests/test_runner_mocked.py`)
```python
import asyncio
import json
from pathlib import Path
from llm_pop_quiz_bench.core.runner import run_quiz
from llm_pop_quiz_bench.adapters.base import ChatAdapter

class MockAdapter:
    id = "mock:adapter"
    async def send(self, messages, params=None):
        return {
            "text": '{"choice":"C","reason":"Fun."}',
            "tokens_in": 10,
            "tokens_out": 5,
            "latency_ms": 50,
        }

async def _run(tmp_path: Path):
    # Minimal quiz dict with 1 Q
    quiz = {
        "id": "mock-quiz",
        "title": "Mock Quiz",
        "source": {"publication":"X","url":"https://x"},
        "questions": [{
            "id": "Q1",
            "text": "Pick one:",
            "options": [{"id":"A","text":"A"},{"id":"B","text":"B"},{"id":"C","text":"C"}]
        }]
    }
    out_dir = tmp_path / "results"
    out_dir.mkdir()
    await run_quiz(
        quiz=quiz,
        adapters=[MockAdapter()],
        run_id="test-run",
        results_dir=out_dir
    )
    raw_files = list((out_dir / "raw").glob("*.jsonl"))
    assert raw_files, "Expected a raw JSONL output"

def test_runner_mocked(tmp_path):
    asyncio.run(_run(tmp_path))
```

### 13.5 Adapter Contracts (`tests/test_adapters_contract.py`)
```python
import asyncio
from llm_pop_quiz_bench.adapters.base import ChatAdapter

async def check_adapter(adapter: ChatAdapter):
    msg = [{"role":"user","content":"Respond in JSON: {\"choice\":\"A\",\"reason\":\"Ok\"}"}]
    res = await adapter.send(msg, params={"temperature": 0.2})
    assert isinstance(res["text"], str)
    assert "latency_ms" in res

# Add parametrization once real adapters exist
def test_contract_placeholder():
    assert True
```

---

## 14) CI (Optional but Recommended)

`.github/workflows/ci.yml`:

```yaml
name: ci
on:
  push: { branches: [ main ] }
  pull_request: {}
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
        shell: bash
      - run: source .venv/bin/activate && ruff check .
        shell: bash
      - run: source .venv/bin/activate && pytest -q
        shell: bash
```

> CI should not hit real provider APIs. Keep adapter tests mocked.

---

## 15) Weekly Playbook (`docs/PLAYBOOK.md`)

1. Add a new **real** quiz YAML with `source` URL and `notes`.
2. Update `config/run.yaml` with the quiz path and models.
3. Run:  
   `python -m llm_pop_quiz_bench.cli.main quiz:run --quiz quizzes/<new>.yaml --models all --reps 3`
4. Generate Markdown/CSV:  
   `python -m llm_pop_quiz_bench.cli.main quiz:report --run <run_id>`
5. Paste the Markdown table + commentary into your blog/LinkedIn.
6. Commit `results/` artifacts to a `results` folder or branch.

---

## 16) Implementation Milestones (Agent Checklist)

1. **Scaffold** folders/files as per structure; add `requirements.txt`, `.env.example`.
2. Implement **types**, **prompt renderer**, **utils** (JSON parsing/repair).
3. Implement **store** (JSONL/CSV writers), **reporter** (Markdown/CSV).
4. Implement **scorer** (DSL: `mostly`, `mostlyTag`, `scoreRange`).
5. Implement **adapters**: start with 2–3 providers + `http_generic`.
6. Implement **runner** (async, retries/backoff, timeouts, metrics).
7. Implement **CLI (Typer)**: `quiz:run`, `quiz:score`, `quiz:report`, `quiz:demo`.
8. Add **tests** (unit + mocked E2E); ensure `pytest` green; add `ruff` lint.
9. Produce a **demo run** and a sample **Markdown** report file.

**Acceptance Criteria**
- Single command runs a sample quiz across at least **2 providers** and outputs JSONL/CSV/MD.
- Robust to non-JSON replies (repair step).
- Clear docs; adding a new model/quiz requires **no code changes**, only YAML.

---

## 17) Troubleshooting Notes

- If a model refuses (policy), mark `refused=True` and continue; mention in report.
- Keep temperature low to reduce randomness (`0.2` default).
- Ensure adapter timeouts and backoff for **429/5xx**.
- Don’t publish full quiz text; cite sources and use short fair-use snippets only.

---

## 18) Example CLI Session (Happy Path)

```bash
# 1) Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill keys

# 2) Lint & tests first (TDD-friendly)
ruff check .
pytest -q

# 3) Demo run
python -m llm_pop_quiz_bench.cli.main quiz:demo

# 4) Real run
python -m llm_pop_quiz_bench.cli.main quiz:run \
  --quiz quizzes/sample_ninja_turtles.yaml \
  --models openai:gpt-4o,anthropic:claude-3-5-sonnet \
  --reps 1

# 5) Report
python -m llm_pop_quiz_bench.cli.main quiz:report --run <run_id>
```

---

### End of Build Spec

This Markdown file is designed for an agentic coding agent to implement the project end‑to‑end, with **full setup**, **tests**, and a clear **iteration loop**. If any ambiguity arises (e.g., exact provider parameter names), implement sensible defaults and leave TODOs in code comments and `README.md`. 

