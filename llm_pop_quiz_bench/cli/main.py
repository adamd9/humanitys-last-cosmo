from __future__ import annotations

import uuid
from pathlib import Path

import typer

from ..adapters.anthropic_adapter import AnthropicAdapter
from ..adapters.openai_adapter import OpenAIAdapter
from ..core.quiz_converter import text_to_yaml
from ..core.runner import run_sync

app = typer.Typer()


@app.command("quiz:run")
def quiz_run(quiz: Path, models: str = "openai:gpt-4o,anthropic:claude-3-5-sonnet") -> None:
    run_id = uuid.uuid4().hex
    adapters = []
    for m in models.split(","):
        provider, model = m.split(":", 1)
        if provider == "openai":
            adapters.append(OpenAIAdapter(model=model, api_key_env="OPENAI_API_KEY"))
        elif provider == "anthropic":
            adapters.append(AnthropicAdapter(model=model, api_key_env="ANTHROPIC_API_KEY"))
    run_sync(quiz_path=quiz, adapters=adapters, run_id=run_id, results_dir=Path("results"))
    typer.echo(f"Run ID: {run_id}")


@app.command("quiz:demo")
def quiz_demo() -> None:
    quiz_run(Path("quizzes/sample_ninja_turtles.yaml"))


@app.command("quiz:convert")
def quiz_convert(text_file: Path, model: str = "gpt-4o") -> None:
    """Convert a raw quiz text file to YAML using OpenAI."""
    text = text_file.read_text(encoding="utf-8")
    yaml_text = text_to_yaml(text, model=model)
    out_path = text_file.with_suffix(".yaml")
    out_path.write_text(yaml_text, encoding="utf-8")
    typer.echo(f"YAML written to {out_path}")


if __name__ == "__main__":
    app()
