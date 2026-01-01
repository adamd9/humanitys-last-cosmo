# LLM Pop Quiz Bench

Minimal prototype implementing instructions from `llm_pop_quiz_bench_python_build_spec.md`.

After installing dependencies you can run the demo quiz:

```bash
python -m llm_pop_quiz_bench.cli.main quiz:demo
```

## API server (local)

Start the backend API with:

```bash
uvicorn llm_pop_quiz_bench.api.app:app --reload
```

Then open:
http://127.0.0.1:8000

To convert a raw quiz text file to JSON using OpenAI, run:

```bash
python -m llm_pop_quiz_bench.cli.main quiz:convert path/to/quiz.txt
```

Set `LLM_POP_QUIZ_ENV=mock` to use internal mock adapters instead of real API
calls. The default environment is `real`.

## Runtime data directory

All run data is stored under a single runtime directory. Configure it with:

```bash
export LLM_POP_QUIZ_RUNTIME_DIR=/path/to/runtime-data
```

If unset, the default is `runtime-data/` at the project root.

Outputs are written under:
- `runtime-data/db/quizbench.sqlite3` for raw run data
- `runtime-data/assets/<run_id>/` for reports and charts

## Visualizing results with PandasAI

If [PandasAI](https://github.com/gventuri/pandas-ai) is installed, the reporter
will attempt to generate additional charts using a language-model-driven
analysis of the raw quiz data. PandasAI is an optional dependency and is not
required for basic operation.
