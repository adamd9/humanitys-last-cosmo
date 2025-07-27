# Codex Setup Guide

These steps install dependencies and prepare the environment so tests and CLI commands work correctly.

1. **Create and activate a virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. **Install project requirements**
   ```bash
   pip install -r requirements.txt
   ```
3. **Copy and fill environment variables**
   ```bash
   cp .env.example .env
   # edit .env and provide API keys like OPENAI_API_KEY
   ```
4. **Run lint and tests**
   ```bash
   ruff check .
   pytest -q
   ```
5. **Optionally format code**
   ```bash
   ruff format .
   ```

After these steps you can run the demo or any quiz using the CLI, for example:
```bash
python -m llm_pop_quiz_bench.cli.main quiz:demo
```
