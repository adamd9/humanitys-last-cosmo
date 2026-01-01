from __future__ import annotations

import base64
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..core import reporter
from ..core.model_config import model_config_loader
from ..core.openrouter import fetch_user_models, normalize_models, strip_prefix
from ..core.quiz_meta import build_quiz_meta
from ..core.quiz_converter import convert_to_yaml
from ..core.runtime_data import build_runtime_paths, get_runtime_paths
from ..core.runner import run_sync
from ..core.logging_utils import rotate_log_if_needed
from ..core.sqlite_store import (
    connect,
    delete_quiz,
    delete_assets_for_run,
    fetch_assets,
    fetch_quiz_record,
    fetch_quiz_yaml,
    fetch_quizzes,
    fetch_results,
    fetch_run,
    fetch_runs,
    insert_run,
    mark_stale_runs_failed,
    update_run_status,
    upsert_quiz,
)

app = FastAPI()


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    runtime_paths = get_runtime_paths()
    detail = exc.errors()
    _append_server_log(
        runtime_paths.logs_dir / "server.log",
        f"validation_error method={request.method} path={request.url.path} detail={detail} body={exc.body}",
    )
    return JSONResponse(status_code=422, content={"detail": detail})
WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
STATIC_ROOT = WEB_ROOT / "static"

if STATIC_ROOT.exists():
    app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")


def _strip_fenced_yaml(text: str) -> str:
    trimmed = text.strip()
    if "```" in trimmed:
        start = trimmed.find("```")
        end = trimmed.find("```", start + 3)
        if end != -1:
            block = trimmed[start + 3 : end]
            lines = block.splitlines()
            if lines and lines[0].strip().startswith("yaml"):
                lines = lines[1:]
            return "\n".join(lines).strip()
    return trimmed


def _sanitize_yaml(text: str) -> str:
    keys_to_quote = {"title", "notes", "text", "result", "description", "publication", "url"}
    lines = []
    for line in text.splitlines():
        if ":" not in line:
            lines.append(line)
            continue
        prefix, value = line.split(":", 1)
        key = prefix.strip().lstrip("-").strip()
        stripped = value.lstrip()
        if key in keys_to_quote:
            if stripped.startswith(("\"", "'", "[", "{")):
                lines.append(line)
                continue
            if stripped in ("null", "true", "false"):
                lines.append(line)
                continue
            if any(ch.isdigit() for ch in stripped[:1]):
                lines.append(line)
                continue
            if ":" in stripped:
                escaped = stripped.replace("\\", "\\\\").replace("\"", "\\\"")
                lines.append(f"{prefix}: \"{escaped}\"")
                continue
        lines.append(line)
    return "\n".join(lines)


def _append_server_log(path: Path, message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    rotate_log_if_needed(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def _log_quiz_yaml_failure(
    runtime_paths,
    context: str,
    yaml_text: str,
    error: Exception | None = None,
) -> None:
    log_path = runtime_paths.logs_dir / "quiz_conversion.log"
    snippet = yaml_text[:2000].replace("\n", "\\n")
    detail = f" error={error}" if error else ""
    _append_server_log(log_path, f"{context} invalid_quiz_yaml{detail} yaml_snippet={snippet}")


def _invalid_quiz_yaml_detail(reason: str) -> str:
    return f"Invalid quiz YAML returned ({reason}; see logs/quiz_conversion.log)"


@app.on_event("startup")
def cleanup_stale_runs() -> None:
    runtime_paths = get_runtime_paths()
    conn = connect(runtime_paths.db_path)
    run_ids = mark_stale_runs_failed(conn)
    conn.close()
    if run_ids:
        for run_id in run_ids:
            log_path = runtime_paths.logs_dir / f"{run_id}.log"
            _append_server_log(log_path, "Server restarted; run marked as failed.")


class RunRequest(BaseModel):
    quiz_id: str
    models: list[str] | None = None
    group: str | None = None
    generate_report: bool = True


async def _save_upload(upload: UploadFile, dest_dir: Path) -> Path:
    suffix = Path(upload.filename or "").suffix
    filename = f"{uuid.uuid4().hex}{suffix}"
    path = dest_dir / filename
    content = await upload.read()
    path.write_bytes(content)
    return path


def _build_raw_preview(raw_payload: dict | None) -> dict | None:
    if not raw_payload:
        return None
    if raw_payload.get("type") == "text":
        return {"type": "text", "text": raw_payload.get("text", "")}
    if raw_payload.get("type") == "image":
        image_path = Path(raw_payload.get("path", ""))
        if not image_path.exists():
            return None
        mime = raw_payload.get("mime") or "image/png"
        data_url = (
            f"data:{mime};base64,"
            f"{base64.b64encode(image_path.read_bytes()).decode('ascii')}"
        )
        return {
            "type": "image",
            "data_url": data_url,
            "mime": mime,
            "filename": image_path.name,
        }
    return None


def _run_and_report(
    quiz_path: Path,
    adapters: list,
    run_id: str,
    runtime_root: Path,
    generate_report: bool,
) -> None:
    run_sync(quiz_path, adapters, run_id, runtime_root)
    if generate_report:
        runtime_paths = build_runtime_paths(runtime_root)
        conn = connect(runtime_paths.db_path)
        update_run_status(conn, run_id, "reporting")
        conn.close()
        try:
            reporter.generate_markdown_report(run_id, runtime_root)
        except Exception:
            conn = connect(runtime_paths.db_path)
            update_run_status(conn, run_id, "failed")
            conn.close()
            raise
        conn = connect(runtime_paths.db_path)
        update_run_status(conn, run_id, "completed")
        conn.close()


def _report_only(run_id: str, runtime_root: Path) -> None:
    runtime_paths = build_runtime_paths(runtime_root)
    conn = connect(runtime_paths.db_path)
    update_run_status(conn, run_id, "reporting")
    conn.close()
    try:
        reporter.generate_markdown_report(run_id, runtime_root)
    except Exception:
        conn = connect(runtime_paths.db_path)
        update_run_status(conn, run_id, "failed")
        conn.close()
        raise
    conn = connect(runtime_paths.db_path)
    update_run_status(conn, run_id, "completed")
    conn.close()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    index_path = WEB_ROOT / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    favicon_path = WEB_ROOT / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(favicon_path)
    png_fallback = STATIC_ROOT / "logo.png"
    if png_fallback.exists():
        return FileResponse(png_fallback, media_type="image/png")
    raise HTTPException(status_code=404, detail="Favicon not found")


@app.get("/api/models")
def list_models() -> dict:
    use_mocks = os.environ.get("LLM_POP_QUIZ_ENV", "real").lower() == "mock"
    overrides = model_config_loader.models
    models = []
    if use_mocks:
        for override in overrides.values():
            models.append(
                {
                    "id": override.id,
                    "model": override.model,
                    "name": override.model,
                    "description": override.description,
                    "context_length": None,
                    "pricing": None,
                    "available": True,
                }
            )
    else:
        try:
            raw_models = fetch_user_models()
        except Exception:
            raw_models = []
        for entry in normalize_models(raw_models):
            override = overrides.get(entry["id"])
            description = entry["description"]
            if override and override.description:
                description = override.description
            models.append(
                {
                    "id": entry["id"],
                    "model": entry["model"],
                    "name": entry["name"],
                    "description": description,
                    "context_length": entry.get("context_length"),
                    "pricing": entry.get("pricing"),
                    "available": bool(os.environ.get("OPENROUTER_API_KEY")),
                }
            )
    return {"models": models, "groups": model_config_loader.model_groups}


@app.get("/api/quizzes")
def list_quizzes() -> dict:
    runtime_paths = get_runtime_paths()
    conn = connect(runtime_paths.db_path)
    quizzes = fetch_quizzes(conn)
    conn.close()
    return {"quizzes": quizzes}


@app.get("/api/quizzes/{quiz_id}")
def get_quiz(quiz_id: str) -> dict:
    runtime_paths = get_runtime_paths()
    conn = connect(runtime_paths.db_path)
    record = fetch_quiz_record(conn, quiz_id)
    conn.close()
    if not record:
        raise HTTPException(status_code=404, detail="Quiz not found")
    raw_preview = _build_raw_preview(record.get("raw_payload"))
    return {
        "quiz": record["quiz"],
        "quiz_yaml": record["quiz_yaml"],
        "quiz_meta": build_quiz_meta(record["quiz"]),
        "raw_payload": record.get("raw_payload"),
        "raw_preview": raw_preview,
    }


@app.delete("/api/quizzes/{quiz_id}")
def remove_quiz(quiz_id: str) -> dict:
    runtime_paths = get_runtime_paths()
    conn = connect(runtime_paths.db_path)
    record = fetch_quiz_record(conn, quiz_id)
    if not record:
        conn.close()
        raise HTTPException(status_code=404, detail="Quiz not found")

    run_ids = delete_quiz(conn, quiz_id)
    conn.close()

    quiz_path = runtime_paths.quizzes_dir / f"{quiz_id}.yaml"
    if quiz_path.exists():
        quiz_path.unlink()

    for run_id in run_ids:
        run_assets_dir = runtime_paths.assets_dir / run_id
        if run_assets_dir.exists():
            shutil.rmtree(run_assets_dir, ignore_errors=True)

    return {"status": "deleted", "quiz_id": quiz_id, "runs_removed": len(run_ids)}


@app.post("/api/quizzes/parse")
async def parse_quiz(
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
    model: str | None = Form(None),
) -> dict:
    if not text and not file:
        raise HTTPException(status_code=400, detail="Provide text or image file")

    runtime_paths = get_runtime_paths()

    image_bytes = None
    image_mime = None
    text_input = text
    raw_payload = {}
    if file is not None:
        upload_path = await _save_upload(file, runtime_paths.uploads_dir)
        image_bytes = upload_path.read_bytes()
        image_mime = file.content_type or "image/png"
        text_input = None
        raw_payload = {
            "type": "image",
            "path": str(upload_path),
            "mime": image_mime,
        }
    elif text_input:
        raw_payload = {"type": "text", "text": text_input}

    yaml_text = convert_to_yaml(
        text=text_input,
        image_bytes=image_bytes,
        image_mime=image_mime,
        model=model,
    )
    yaml_text = _strip_fenced_yaml(yaml_text)
    try:
        quiz_def = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        yaml_text = _sanitize_yaml(yaml_text)
        try:
            quiz_def = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc2:
            _log_quiz_yaml_failure(runtime_paths, "parse_quiz", yaml_text, error=exc2)
            raise HTTPException(
                status_code=400,
                detail=_invalid_quiz_yaml_detail("YAML parse error"),
            ) from exc2
    if not quiz_def or "id" not in quiz_def:
        _log_quiz_yaml_failure(runtime_paths, "parse_quiz", yaml_text)
        raise HTTPException(
            status_code=400,
            detail=_invalid_quiz_yaml_detail("missing required id field"),
        )

    quiz_def["id"] = uuid.uuid4().hex
    yaml_text = yaml.safe_dump(quiz_def, sort_keys=False, allow_unicode=False)

    conn = connect(runtime_paths.db_path)
    upsert_quiz(conn, quiz_def, yaml_text, raw_payload)
    conn.close()
    return {
        "quiz": quiz_def,
        "quiz_yaml": yaml_text,
        "quiz_meta": build_quiz_meta(quiz_def),
        "raw_payload": raw_payload,
        "raw_preview": _build_raw_preview(raw_payload),
    }


@app.post("/api/quizzes/{quiz_id}/reprocess")
async def reprocess_quiz(
    quiz_id: str,
    model: str | None = Form(None),
) -> dict:
    runtime_paths = get_runtime_paths()
    conn = connect(runtime_paths.db_path)
    record = fetch_quiz_record(conn, quiz_id)
    conn.close()
    if not record:
        raise HTTPException(status_code=404, detail="Quiz not found")

    raw_payload = record.get("raw_payload") or {}
    if not raw_payload:
        raise HTTPException(status_code=400, detail="Quiz is missing raw input data")

    yaml_text = None
    image_bytes = None
    image_mime = None
    text_input = None
    if raw_payload.get("type") == "text":
        text_input = raw_payload.get("text")
    elif raw_payload.get("type") == "image":
        image_path = Path(raw_payload.get("path", ""))
        image_mime = raw_payload.get("mime") or "image/png"
        if not image_path.exists():
            raise HTTPException(
                status_code=500,
                detail="Stored raw image is missing; cannot reprocess",
            )
        image_bytes = image_path.read_bytes()
    else:
        raise HTTPException(status_code=400, detail="Unsupported raw input type")

    yaml_text = convert_to_yaml(
        text=text_input,
        image_bytes=image_bytes,
        image_mime=image_mime,
        model=model,
    )
    yaml_text = _strip_fenced_yaml(yaml_text)
    try:
        quiz_def = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        yaml_text = _sanitize_yaml(yaml_text)
        try:
            quiz_def = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc2:
            _log_quiz_yaml_failure(runtime_paths, "reprocess_quiz", yaml_text, error=exc2)
            raise HTTPException(
                status_code=400,
                detail=_invalid_quiz_yaml_detail("YAML parse error"),
            ) from exc2
    if not quiz_def or "id" not in quiz_def:
        _log_quiz_yaml_failure(runtime_paths, "reprocess_quiz", yaml_text)
        raise HTTPException(
            status_code=400,
            detail=_invalid_quiz_yaml_detail("missing required id field"),
        )

    conn = connect(runtime_paths.db_path)
    upsert_quiz(conn, quiz_def, yaml_text, raw_payload)
    conn.close()
    return {
        "quiz": quiz_def,
        "quiz_yaml": yaml_text,
        "quiz_meta": build_quiz_meta(quiz_def),
        "raw_payload": raw_payload,
        "raw_preview": _build_raw_preview(raw_payload),
    }


@app.post("/api/runs")
def create_run(req: RunRequest, background_tasks: BackgroundTasks) -> dict:
    runtime_paths = get_runtime_paths()
    use_mocks = os.environ.get("LLM_POP_QUIZ_ENV", "real").lower() == "mock"

    conn = connect(runtime_paths.db_path)
    quiz_yaml = fetch_quiz_yaml(conn, req.quiz_id)
    conn.close()
    if not quiz_yaml:
        raise HTTPException(status_code=404, detail="Quiz not found")

    quiz_path = runtime_paths.quizzes_dir / f"{req.quiz_id}.yaml"
    quiz_path.write_text(quiz_yaml, encoding="utf-8")

    if not req.models and not req.group:
        raise HTTPException(status_code=400, detail="Select at least one model or group")

    if not use_mocks and not os.environ.get("OPENROUTER_API_KEY"):
        raise HTTPException(status_code=400, detail="OPENROUTER_API_KEY is required")

    if req.models:
        model_ids = [strip_prefix(model_id) for model_id in req.models]
        adapters = model_config_loader.create_adapters(model_ids, use_mocks)
    elif req.group:
        try:
            model_ids = model_config_loader.model_groups[req.group]
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown model group: {req.group}") from exc
        adapters = model_config_loader.create_adapters(model_ids, use_mocks)

    if not adapters:
        raise HTTPException(status_code=400, detail="No available models to run")

    run_id = uuid.uuid4().hex
    conn = connect(runtime_paths.db_path)
    insert_run(
        conn,
        run_id=run_id,
        quiz_id=req.quiz_id,
        status="queued",
        models=[adapter.id for adapter in adapters],
        settings={"group": req.group} if req.group else None,
    )
    conn.close()
    background_tasks.add_task(
        _run_and_report,
        quiz_path,
        adapters,
        run_id,
        runtime_paths.root,
        req.generate_report,
    )
    return {"run_id": run_id}


@app.get("/api/runs")
def list_runs() -> dict:
    runtime_paths = get_runtime_paths()
    conn = connect(runtime_paths.db_path)
    runs = fetch_runs(conn)
    conn.close()
    return {"runs": runs}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    runtime_paths = get_runtime_paths()
    conn = connect(runtime_paths.db_path)
    run = fetch_run(conn, run_id)
    assets = fetch_assets(conn, run_id)
    conn.close()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    run_assets_dir = runtime_paths.assets_dir / run_id
    for asset in assets:
        path = Path(asset["path"])
        try:
            rel = path.relative_to(run_assets_dir)
            asset["url"] = f"/api/assets/{run_id}/{rel.as_posix()}"
        except ValueError:
            asset["url"] = None
    return {"run": run, "assets": assets}


@app.post("/api/runs/{run_id}/report")
def rerun_report(run_id: str, background_tasks: BackgroundTasks) -> dict:
    runtime_paths = get_runtime_paths()
    conn = connect(runtime_paths.db_path)
    run = fetch_run(conn, run_id)
    if not run:
        conn.close()
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("status") in {"queued", "running", "reporting"}:
        conn.close()
        raise HTTPException(status_code=400, detail="Run is still in progress")
    results = fetch_results(conn, run_id)
    if not results:
        conn.close()
        raise HTTPException(status_code=400, detail="Run has no results to analyze")
    delete_assets_for_run(conn, run_id)
    conn.close()

    run_assets_dir = runtime_paths.assets_dir / run_id
    for subdir in ("reports", "charts", "pandasai_charts"):
        target = run_assets_dir / subdir
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)

    _append_server_log(runtime_paths.logs_dir / f"{run_id}.log", "Re-running report analysis.")
    background_tasks.add_task(_report_only, run_id, runtime_paths.root)
    return {"status": "queued", "run_id": run_id}


@app.get("/api/assets/{run_id}/{asset_path:path}")
def get_asset(run_id: str, asset_path: str) -> FileResponse:
    runtime_paths = get_runtime_paths()
    run_assets_dir = runtime_paths.assets_dir / run_id
    target = (run_assets_dir / asset_path).resolve()
    if not str(target).startswith(str(run_assets_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid asset path")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(target)


@app.get("/api/runs/{run_id}/results")
def get_run_results(run_id: str) -> dict:
    runtime_paths = get_runtime_paths()
    conn = connect(runtime_paths.db_path)
    rows = fetch_results(conn, run_id)
    conn.close()
    return {"results": rows}


@app.get("/api/runs/{run_id}/log")
def get_run_log(run_id: str, tail: int = 300) -> dict:
    runtime_paths = get_runtime_paths()
    log_path = runtime_paths.logs_dir / f"{run_id}.log"
    if not log_path.exists():
        return {"log": "", "exists": False}
    content = log_path.read_text(encoding="utf-8", errors="replace")
    if tail > 0:
        lines = content.splitlines()
        if len(lines) > tail:
            content = "\n".join(lines[-tail:])
    return {"log": content, "exists": True}


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> FileResponse:
    if full_path.startswith("api/") or full_path.startswith("static/"):
        raise HTTPException(status_code=404, detail="Not found")
    index_path = WEB_ROOT / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)
