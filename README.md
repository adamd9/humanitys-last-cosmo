# LLM Pop Quiz Bench

Minimal prototype implementing instructions from `llm_pop_quiz_bench_python_build_spec.md`.

After installing dependencies you can run the demo quiz:

```bash
python -m llm_pop_quiz_bench.cli.main quiz:demo
```

To convert a raw quiz text file to YAML using OpenAI, run:

```bash
python -m llm_pop_quiz_bench.cli.main quiz:convert path/to/quiz.txt
```

Set `LLM_POP_QUIZ_ENV=mock` to use internal mock adapters instead of real API
calls. When running in mock mode, outputs are written to `results/mock/` instead
of `results/`. The default environment is `real`.

## Visualizing results with PandasAI

If [PandasAI](https://github.com/gventuri/pandas-ai) is installed, the reporter
will attempt to generate additional charts using a language-model-driven
analysis of the raw quiz data. PandasAI is an optional dependency and is not
required for basic operation.

