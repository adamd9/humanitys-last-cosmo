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
from ..core.model_config import model_config_loader
from ..core.quiz_converter import text_to_yaml
from ..core.runner import run_sync

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
        models: Comma-separated list of model IDs (e.g., "openai:gpt-4o,anthropic:claude-3-5-sonnet")
        group: Model group name from config (e.g., "default", "openai_comparison", "premium")
    """
    
    # Extract quiz name from filename for directory structure
    quiz_name = quiz.stem  # Gets filename without extension
    run_id = uuid.uuid4().hex
    use_mocks = os.environ.get("LLM_POP_QUIZ_ENV", "real").lower() == "mock"
    
    # Create timestamped run directory with quiz name
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir_name = f"{timestamp}_{quiz_name}_{run_id[:8]}"
    
    if use_mocks:
        results_base_dir = Path("results_mock")
    else:
        results_base_dir = Path("results")
    
    results_dir = results_base_dir / run_dir_name
    
    # Determine which models to use
    if models:
        # Explicit model list provided
        model_ids = [m.strip() for m in models.split(",")]
        selected_models = []
        for model_id in model_ids:
            model_config = model_config_loader.get_model(model_id)
            if model_config:
                selected_models.append(model_config)
            else:
                typer.echo(f"⚠️  Unknown model: {model_id}")
    elif group:
        # Model group provided
        try:
            selected_models = model_config_loader.get_available_models_by_group(group, use_mocks)
            if not selected_models:
                typer.echo(f"❌ No available models in group '{group}'. Check your API keys.")
                raise typer.Exit(1)
        except ValueError as e:
            typer.echo(f"❌ {e}")
            available_groups = model_config_loader.list_available_groups(use_mocks)
            typer.echo(f"Available groups: {', '.join(available_groups)}")
            raise typer.Exit(1)
    else:
        # Default: use all available models from the "default" group
        selected_models = model_config_loader.get_available_models_by_group("default", use_mocks)
        if not selected_models:
            # Fallback to any available models
            selected_models = model_config_loader.get_available_models(use_mocks)
    
    if not selected_models:
        typer.echo("❌ No available models found. Check your API keys.")
        available_groups = model_config_loader.list_available_groups(use_mocks)
        if available_groups:
            typer.echo(f"Available model groups: {', '.join(available_groups)}")
        raise typer.Exit(1)
    
    # Display selected models
    model_names = [model.id for model in selected_models]
    typer.echo(f"🤖 Running benchmark with models: {', '.join(model_names)}")
    
    # Create adapters
    adapters = []
    for model_config in selected_models:
        if model_config.is_available(use_mocks):
            adapter = model_config.create_adapter(use_mocks)
            adapters.append(adapter)
        else:
            typer.echo(f"⚠️  Skipping {model_config.id} - {model_config.api_key_env} not found in environment")
    
    if not adapters:
        typer.echo("❌ No valid adapters created. Check your API keys.")
        raise typer.Exit(1)
    
    typer.echo(f"✅ Running quiz with {len(adapters)} adapter(s)")
    
    # Run the quiz
    run_sync(quiz, adapters, run_id, results_dir)
    
    typer.echo(f"📊 Generating comprehensive report...")
    
    # Generate the report immediately
    reporter.generate_markdown_report(run_id, results_base_dir)
    
    typer.echo(f"🎉 Benchmark complete! Results in: {results_dir}")
    typer.echo(f"📁 Run ID: {run_id}")


@app.command("models")
def list_models() -> None:
    """List all available models and model groups."""
    use_mocks = os.environ.get("LLM_POP_QUIZ_ENV", "real").lower() == "mock"
    
    typer.echo("🤖 Available Models:")
    typer.echo("")
    
    # Group models by provider
    providers = {}
    for model_config in model_config_loader.models.values():
        if model_config.provider not in providers:
            providers[model_config.provider] = []
        providers[model_config.provider].append(model_config)
    
    for provider, models in providers.items():
        typer.echo(f"💻 {provider.upper()}:")
        for model in models:
            status = "✅" if model.is_available(use_mocks) else "❌"
            typer.echo(f"  {status} {model.id} - {model.description}")
        typer.echo("")
    
    typer.echo("📁 Model Groups:")
    typer.echo("")
    
    for group_name, model_ids in model_config_loader.model_groups.items():
        available_count = len(model_config_loader.get_available_models_by_group(group_name, use_mocks))
        total_count = len(model_ids)
        status = "✅" if available_count > 0 else "❌"
        typer.echo(f"  {status} {group_name} ({available_count}/{total_count} available)")
        for model_id in model_ids:
            model_config = model_config_loader.get_model(model_id)
            if model_config:
                model_status = "✅" if model_config.is_available(use_mocks) else "❌"
                typer.echo(f"    {model_status} {model_id}")
    
    typer.echo("")
    typer.echo("📝 Usage Examples:")
    typer.echo("  # Use default models")
    typer.echo("  python -m llm_pop_quiz_bench.cli.main benchmark quiz.yaml")
    typer.echo("")
    typer.echo("  # Use specific model group")
    typer.echo("  python -m llm_pop_quiz_bench.cli.main benchmark quiz.yaml --group openai_comparison")
    typer.echo("")
    typer.echo("  # Use specific models")
    typer.echo("  python -m llm_pop_quiz_bench.cli.main benchmark quiz.yaml --models openai:gpt-4o,anthropic:claude-3-5-sonnet")


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
