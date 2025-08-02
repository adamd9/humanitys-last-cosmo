from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

import typer
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from ..adapters.anthropic_adapter import AnthropicAdapter
from ..adapters.google_adapter import GoogleAdapter
from ..adapters.mock_adapter import MockAdapter
from ..adapters.openai_adapter import OpenAIAdapter
from ..core import reporter
from ..core.quiz_converter import text_to_yaml
from ..core.runner import run_sync

app = typer.Typer()


@app.command("quiz:run")
def quiz_run(quiz: Path, models: str = None) -> None:
    """Run a quiz with all available models (default) or specified models for testing."""

    run_id = uuid.uuid4().hex
    adapters = []
    use_mocks = os.environ.get("LLM_POP_QUIZ_ENV", "real").lower() == "mock"
    
    # Create timestamped run directory
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir_name = f"{timestamp}_{run_id[:8]}"
    
    if use_mocks:
        results_base_dir = Path("results_mock")
    else:
        results_base_dir = Path("results")
    
    results_dir = results_base_dir / run_dir_name
    
    # If no models specified, use all available models
    if models is None:
        available_models = []
        if use_mocks:
            available_models = ["openai:gpt-4o", "anthropic:claude-3-5-sonnet", "google:gemini-1.5-flash"]
        else:
            if os.environ.get("OPENAI_API_KEY"):
                available_models.append("openai:gpt-4o")
            if os.environ.get("ANTHROPIC_API_KEY"):
                available_models.append("anthropic:claude-3-5-sonnet")
            if os.environ.get("GOOGLE_API_KEY"):
                available_models.append("google:gemini-1.5-flash")
        
        if not available_models:
            typer.echo("❌ No API keys found. Please set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY")
            raise typer.Exit(1)
        
        models = ",".join(available_models)
        typer.echo(f"🤖 Using all available models: {models}")
    
    for m in models.split(","):
        provider, model = m.split(":", 1)
        if use_mocks:
            adapters.append(MockAdapter(model=f"{provider}:{model}"))
        elif provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY")
            if api_key:
                adapters.append(OpenAIAdapter(model=model, api_key_env="OPENAI_API_KEY"))
            else:
                typer.echo(f"⚠️  Skipping {provider}:{model} - OPENAI_API_KEY not found in environment", err=True)
        elif provider == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if api_key:
                adapters.append(AnthropicAdapter(model=model, api_key_env="ANTHROPIC_API_KEY"))
            else:
                typer.echo(f"⚠️  Skipping {provider}:{model} - ANTHROPIC_API_KEY not found in environment", err=True)
        elif provider == "google":
            api_key = os.environ.get("GOOGLE_API_KEY")
            if api_key:
                adapters.append(GoogleAdapter(model=model, api_key_env="GOOGLE_API_KEY"))
            else:
                typer.echo(f"⚠️  Skipping {provider}:{model} - GOOGLE_API_KEY not found in environment", err=True)
        else:
            typer.echo(f"⚠️  Skipping {provider}:{model} - Unknown provider '{provider}'", err=True)

    if not adapters:
        typer.echo("❌ No valid adapters available. Please check your API keys or use mock mode with LLM_POP_QUIZ_ENV=mock", err=True)
        raise typer.Exit(1)

    typer.echo(f"✅ Running quiz with {len(adapters)} adapter(s)")
    run_sync(
        quiz_path=quiz,
        adapters=adapters,
        run_id=run_id,
        results_dir=results_dir,
    )
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


@app.command("quiz:report")
def quiz_report(run_id: str, results_dir: Path = Path("results")) -> None:
    """Generate Markdown and CSV summaries for a run."""
    # The new directory structure doesn't need special handling here
    # The reporter will automatically find the timestamped directory
    reporter.generate_markdown_report(run_id, results_dir)


if __name__ == "__main__":
    app()
