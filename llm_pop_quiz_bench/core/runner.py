from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ..adapters.base import ChatAdapter
from .prompt import PromptContext, render_prompt
from .types import QAResult
from .utils import parse_choice_json
from .runtime_data import build_runtime_paths, get_runtime_paths
from .sqlite_store import connect, insert_results, insert_run, update_run_status, upsert_quiz


def _extract_actual_error(exception: Exception) -> str:
    """Extract the actual error message from RetryError and other exception wrappers."""
    # Handle RetryError from tenacity
    if hasattr(exception, 'last_attempt') and exception.last_attempt:
        if hasattr(exception.last_attempt, 'exception') and exception.last_attempt.exception():
            return str(exception.last_attempt.exception())
    
    # Handle other wrapped exceptions
    if hasattr(exception, '__cause__') and exception.__cause__:
        return str(exception.__cause__)
    
    if hasattr(exception, '__context__') and exception.__context__:
        return str(exception.__context__)
    
    # Fallback to the original exception string
    return str(exception)


def _get_model_params(adapter) -> dict:
    """Get model-specific parameters from the adapter's configuration."""
    # Use the model's configured defaultParams from models.yaml
    if hasattr(adapter, 'default_params'):
        return adapter.default_params.copy()
    else:
        # Fallback to basic temperature if no specific config available
        return {"temperature": 0.2}


def _append_log(path: Path, message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    line = f"[{timestamp}] {message}"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")
    print(line)


async def run_quiz(
    quiz_path: Path, adapters: list[ChatAdapter], run_id: str, runtime_dir: Path | None = None
) -> None:
    quiz_yaml = quiz_path.read_text(encoding="utf-8")
    quiz = yaml.safe_load(quiz_yaml)

    questions = quiz["questions"]

    successful_adapters = []
    failed_adapters = []

    runtime_paths = get_runtime_paths() if runtime_dir is None else build_runtime_paths(runtime_dir)

    log_path = runtime_paths.logs_dir / f"{run_id}.log"
    conn = connect(runtime_paths.db_path)
    upsert_quiz(conn, quiz, quiz_yaml)
    insert_run(
        conn,
        run_id=run_id,
        quiz_id=quiz["id"],
        status="running",
        models=[adapter.id for adapter in adapters],
    )
    _append_log(log_path, f"Run {run_id} started for quiz {quiz['id']}.")
    
    for adapter in adapters:
        try:
            _append_log(log_path, f"Testing model: {adapter.id}")
            model_records: list[dict] = []
            
            for idx, q in enumerate(questions, start=1):
                try:
                    ctx = PromptContext(
                        quiz_title=quiz["title"],
                        q_num=idx,
                        q_total=len(questions),
                        question_text=q["text"],
                        options=[opt["text"] for opt in q["options"]],
                    )
                    prompt = render_prompt(ctx)
                    messages = [{"role": "user", "content": prompt}]
                    
                    # Build parameters based on model capabilities
                    params = _get_model_params(adapter)
                    
                    start = time.perf_counter()
                    resp = await adapter.send(messages, params=params)
                    latency_ms = int((time.perf_counter() - start) * 1000)
                    data = parse_choice_json(resp["text"])
                    if not data:
                        data = {"choice": "", "reason": "", "additional_thoughts": "", "refused": True}
                    rec = QAResult(
                        question_id=q["id"],
                        choice=data.get("choice", ""),
                        reason=data.get("reason", ""),
                        additional_thoughts=data.get("additional_thoughts", ""),
                        refused=data.get("refused", False),
                        latency_ms=latency_ms,
                        tokens_in=resp.get("tokens_in"),
                        tokens_out=resp.get("tokens_out"),
                    )
                    model_records.append(rec.__dict__)
                    
                except Exception as e:
                    # Extract the actual error from RetryError or other wrappers
                    actual_error = _extract_actual_error(e)
                    _append_log(
                        log_path,
                        f"Question {idx} failed for {adapter.id}: {actual_error[:150]}",
                    )
                    # Record a failed attempt for this question
                    rec = QAResult(
                        question_id=q["id"],
                        choice="",
                        reason=f"Error: {actual_error[:150]}",
                        additional_thoughts="",
                        refused=True,
                        latency_ms=0,
                        tokens_in=0,
                        tokens_out=0,
                    )
                    model_records.append(rec.__dict__)
                    continue
            
            # If we got here, the adapter worked (even if some questions failed)
            _append_log(log_path, f"Model {adapter.id} completed successfully")
            successful_adapters.append(adapter)
            
        except Exception as e:
            actual_error = _extract_actual_error(e)
            _append_log(log_path, f"Model {adapter.id} failed completely: {actual_error}")
            failed_adapters.append((adapter.id, actual_error))
            continue
        insert_results(conn, run_id, quiz["id"], adapter.id, model_records)

    # Print summary of model results
    _append_log(log_path, "=" * 60)
    _append_log(log_path, "BENCHMARK SUMMARY")
    _append_log(log_path, "=" * 60)
    
    if successful_adapters:
        _append_log(log_path, f"Successful models ({len(successful_adapters)}):")
        for adapter in successful_adapters:
            _append_log(log_path, f" - {adapter.id}")
    
    if failed_adapters:
        _append_log(log_path, f"Failed models ({len(failed_adapters)}):")
        for model_id, error in failed_adapters:
            _append_log(log_path, f" - {model_id}: {error[:80]}...")
    
    if not successful_adapters:
        _append_log(log_path, "WARNING: No models completed successfully!")
        _append_log(log_path, "Check your API keys and model access permissions.")
    else:
        _append_log(log_path, f"Results saved for {len(successful_adapters)} working model(s)")
    
    _append_log(log_path, "=" * 60)
    _append_log(log_path, "Run complete. Waiting on reports if enabled.")

    update_run_status(conn, run_id, "completed")
    conn.close()


def run_sync(*args, **kwargs) -> None:
    asyncio.run(run_quiz(*args, **kwargs))
