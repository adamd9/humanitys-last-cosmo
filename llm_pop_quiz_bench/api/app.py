from __future__ import annotations

import os
import uuid
from pathlib import Path

import yaml
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..core import reporter
from ..core.model_config import model_config_loader
from ..core.quiz_converter import convert_to_yaml
from ..core.runtime_data import get_runtime_paths
from ..core.runner import run_sync
from ..core.sqlite_store import (
    connect,
    fetch_assets,
    fetch_quiz_record,
    fetch_quiz_yaml,
    fetch_quizzes,
    fetch_results,
    fetch_run,
    fetch_runs,
    upsert_quiz,
)

app = FastAPI()
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


def _run_and_report(
    quiz_path: Path,
    adapters: list,
    run_id: str,
    runtime_root: Path,
    generate_report: bool,
) -> None:
    run_sync(quiz_path, adapters, run_id, runtime_root)
    if generate_report:
        reporter.generate_markdown_report(run_id, runtime_root)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    index_path = WEB_ROOT / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)


@app.get("/api/models")
def list_models() -> dict:
    use_mocks = os.environ.get("LLM_POP_QUIZ_ENV", "real").lower() == "mock"
    models = []
    for model in model_config_loader.models.values():
        models.append(
            {
                "id": model.id,
                "provider": model.provider,
                "model": model.model,
                "description": model.description,
                "available": model.is_available(use_mocks),
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
    return {
        "quiz": record["quiz"],
        "quiz_yaml": record["quiz_yaml"],
        "raw_payload": record.get("raw_payload"),
    }


@app.post("/api/quizzes/parse")
async def parse_quiz(
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
    model: str = Form("gpt-4o"),
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
    except yaml.YAMLError:
        yaml_text = _sanitize_yaml(yaml_text)
        quiz_def = yaml.safe_load(yaml_text)
    if not quiz_def or "id" not in quiz_def:
        raise HTTPException(status_code=400, detail="Invalid quiz YAML returned")

    conn = connect(runtime_paths.db_path)
    upsert_quiz(conn, quiz_def, yaml_text, raw_payload)
    conn.close()
    return {"quiz": quiz_def, "quiz_yaml": yaml_text, "raw_payload": raw_payload}


@app.post("/api/quizzes/{quiz_id}/reprocess")
async def reprocess_quiz(
    quiz_id: str,
    model: str = Form("gpt-4o"),
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
    except yaml.YAMLError:
        yaml_text = _sanitize_yaml(yaml_text)
        quiz_def = yaml.safe_load(yaml_text)
    if not quiz_def or "id" not in quiz_def:
        raise HTTPException(status_code=400, detail="Invalid quiz YAML returned")

    conn = connect(runtime_paths.db_path)
    upsert_quiz(conn, quiz_def, yaml_text, raw_payload)
    conn.close()
    return {"quiz": quiz_def, "quiz_yaml": yaml_text, "raw_payload": raw_payload}


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

    if req.models:
        adapters = model_config_loader.create_adapters(req.models, use_mocks)
    elif req.group:
        try:
            group_models = model_config_loader.get_available_models_by_group(req.group, use_mocks)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        adapters = [m.create_adapter(use_mocks) for m in group_models]
    else:
        adapters = model_config_loader.create_adapters(
            [m.id for m in model_config_loader.get_available_models(use_mocks)],
            use_mocks,
        )

    if not adapters:
        raise HTTPException(status_code=400, detail="No available models to run")

    run_id = uuid.uuid4().hex
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
