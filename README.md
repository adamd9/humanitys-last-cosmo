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
calls. The default is `real`.

