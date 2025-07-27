from __future__ import annotations

import uuid
from pathlib import Path
from typing import List

import typer
import yaml

from ..adapters.anthropic_adapter import AnthropicAdapter
from ..adapters.openai_adapter import OpenAIAdapter
from ..core.runner import run_sync

app = typer.Typer()


@app.command("quiz:run")
def quiz_run(quiz: Path, models: str = "openai:gpt-4o,anthropic:claude-3-5-sonnet") -> None:
    run_id = uuid.uuid4().hex
    adapters = []
    for m in models.split(','):
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


if __name__ == "__main__":
    app()
