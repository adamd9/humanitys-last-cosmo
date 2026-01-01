from __future__ import annotations

import os
import uuid
from pathlib import Path

import typer
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from ..core import reporter
from ..core.model_config import model_config_loader
from ..core.openrouter import fetch_user_models, normalize_models, strip_prefix
from ..core.quiz_converter import text_to_yaml
from ..core.runner import run_sync
from ..core.runtime_data import get_runtime_paths

app = typer.Typer()


@app.command("benchmark")
def benchmark(
    quiz: Path, 
    models: str = None, 
    group: str = None
) -> None:
    """Run a complete benchmark: quiz execution + report generation in one step.
    
    Args:
        quiz: Path to the quiz YAML file
        models: Comma-separated list of model IDs (e.g., "openai/gpt-4o")
        group: Model group name from config (e.g., "default", "openai_comparison")
    """
    
    run_id = uuid.uuid4().hex
    use_mocks = os.environ.get("LLM_POP_QUIZ_ENV", "real").lower() == "mock"

    runtime_paths = get_runtime_paths()
    
    if not models and not group:
        typer.echo("❌ Select at least one model or group.")
        raise typer.Exit(1)

    if not use_mocks and not os.environ.get("OPENROUTER_API_KEY"):
        typer.echo("❌ OPENROUTER_API_KEY is required.")
        raise typer.Exit(1)

    # Determine which models to use
    if models:
        model_ids = [strip_prefix(m.strip()) for m in models.split(",")]
    else:
        try:
            model_ids = model_config_loader.model_groups[group]
        except KeyError:
            typer.echo(f"❌ Unknown model group: {group}")
            available_groups = ", ".join(model_config_loader.model_groups.keys())
            if available_groups:
                typer.echo(f"Available model groups: {available_groups}")
            raise typer.Exit(1)

    if not model_ids:
        typer.echo("❌ No models selected.")
        raise typer.Exit(1)

    # Display selected models
    typer.echo(f"🤖 Running benchmark with models: {', '.join(model_ids)}")
    
    # Create adapters
    adapters = model_config_loader.create_adapters(model_ids, use_mocks)
    
    if not adapters:
        typer.echo("❌ No valid adapters created. Check OPENROUTER_API_KEY or mock mode.")
        raise typer.Exit(1)
    
    typer.echo(f"✅ Running quiz with {len(adapters)} adapter(s)")
    
    # Run the quiz
    run_sync(quiz, adapters, run_id, runtime_paths.root)
    
    typer.echo(f"📊 Generating comprehensive report...")
    
    # Generate the report immediately
    reporter.generate_markdown_report(run_id, runtime_paths.root)
    
    typer.echo(f"🎉 Benchmark complete! Assets in: {runtime_paths.assets_dir / run_id}")
    typer.echo(f"📁 Run ID: {run_id}")


@app.command("models")
def list_models() -> None:
    """List all available models and model groups."""
    use_mocks = os.environ.get("LLM_POP_QUIZ_ENV", "real").lower() == "mock"
    
    typer.echo("🤖 Available Models (OpenRouter):")
    typer.echo("")

    if use_mocks:
        models = [
            {
                "id": override.id,
                "description": override.description,
            }
            for override in model_config_loader.models.values()
        ]
    else:
        try:
            raw_models = fetch_user_models()
        except Exception:
            raw_models = []
        models = normalize_models(raw_models)
    overrides = model_config_loader.models
    if not models:
        typer.echo("  (No models returned - check OPENROUTER_API_KEY)")
    for model in models:
        override = overrides.get(model["id"])
        description = model.get("description", "")
        if override and override.description:
            description = override.description
        typer.echo(f"  ✅ {model['id']} - {description}")
    
    typer.echo("📁 Model Groups:")
    typer.echo("")
    
    for group_name, model_ids in model_config_loader.model_groups.items():
        total_count = len(model_ids)
        typer.echo(f"  • {group_name} ({total_count} models)")
        for model_id in model_ids:
            typer.echo(f"    {model_id}")
    
    typer.echo("")
    typer.echo("📝 Usage Examples:")
    typer.echo("  # Use specific models")
    typer.echo("  python -m llm_pop_quiz_bench.cli.main benchmark quiz.yaml --models openai/gpt-4o")
    typer.echo("")
    typer.echo("  # Use specific model group")
    typer.echo("  python -m llm_pop_quiz_bench.cli.main benchmark quiz.yaml --group openai_comparison")
    typer.echo("")
    typer.echo("  # Use specific models")
    typer.echo("  python -m llm_pop_quiz_bench.cli.main benchmark quiz.yaml --models openai/gpt-4o,anthropic/claude-3.5-sonnet")


@app.command("quiz:run")
def quiz_run(quiz: Path, models: str = None) -> None:
    """Run a quiz with specified models for testing."""

    run_id = uuid.uuid4().hex
    use_mocks = os.environ.get("LLM_POP_QUIZ_ENV", "real").lower() == "mock"
    runtime_paths = get_runtime_paths()
    
    if models is None:
        typer.echo("❌ Select at least one model via --models.")
        raise typer.Exit(1)

    if not use_mocks and not os.environ.get("OPENROUTER_API_KEY"):
        typer.echo("❌ OPENROUTER_API_KEY is required.")
        raise typer.Exit(1)

    model_ids = [strip_prefix(m.strip()) for m in models.split(",")]
    adapters = model_config_loader.create_adapters(model_ids, use_mocks)

    if not adapters:
        typer.echo("❌ No valid adapters available. Check OPENROUTER_API_KEY or use mock mode.", err=True)
        raise typer.Exit(1)

    typer.echo(f"✅ Running quiz with {len(adapters)} adapter(s)")
    run_sync(
        quiz_path=quiz,
        adapters=adapters,
        run_id=run_id,
        runtime_dir=runtime_paths.root,
    )
    typer.echo(f"Run ID: {run_id}")


@app.command("quiz:demo")
def quiz_demo() -> None:
    quiz_run(Path("quizzes/sample_ninja_turtles.yaml"), models="openai/gpt-4o")


@app.command("quiz:convert")
def quiz_convert(text_file: Path, model: str | None = None) -> None:
    """Convert a raw quiz text file to YAML using OpenAI."""
    text = text_file.read_text(encoding="utf-8")
    yaml_text = text_to_yaml(text, model=model)
    out_path = text_file.with_suffix(".yaml")
    out_path.write_text(yaml_text, encoding="utf-8")
    typer.echo(f"YAML written to {out_path}")


@app.command("quiz:report")
def quiz_report(run_id: str) -> None:
    """Generate Markdown and CSV summaries for a run."""
    runtime_paths = get_runtime_paths()
    reporter.generate_markdown_report(run_id, runtime_paths.root)


if __name__ == "__main__":
    app()
