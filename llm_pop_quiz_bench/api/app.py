from __future__ import annotations

import base64
import os
import re
import secrets
import shutil
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import json
import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..core import benchmarks, experiments, reporter
from ..core.auth import User, frontend_config, get_current_user
from ..core.model_config import model_config_loader
from ..core.costs import estimate_run_cost, fetch_openrouter_pricing_map
from ..core.openrouter import APP_API_KEY_ENV, fetch_user_models, normalize_models, strip_prefix
from ..core.quiz_meta import build_quiz_meta
from ..core.quiz_converter import convert_to_quiz
from ..core.quotas import check_request_quota, load_quota_config
from ..core.runtime_data import build_runtime_paths, get_runtime_paths
from ..core.runner import run_sync
from ..core.logging_utils import rotate_log_if_needed
from ..core.db_factory import connect

app = FastAPI()

# CORS — the SPA is served from Cloudflare Pages (thelastquiz.net apex +
# app.<domain>) while the API runs on Azure (thelastquiz.drop37.com), so
# browser calls are cross-origin. Allow the public hosts + Pages previews +
# localhost out of the box; LLM_POP_QUIZ_ALLOWED_ORIGINS (comma-separated) can
# add more without a code change.
_cors_origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
]
_cors_origins += [
    o.strip()
    for o in os.environ.get("LLM_POP_QUIZ_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]
_cors_origin_regex = re.compile(
    r"^https://((app|rankings)\.)?(the)?lastquiz\.net$|^https://[a-z0-9-]+\.pages\.dev$"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex.pattern,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


def _allowed_cors_origin(origin: str | None) -> str | None:
    """Return the origin if it passes the same allowlist/regex as the CORS
    middleware, else None. Used to attach CORS headers to error responses that
    are generated outside the middleware (e.g. unhandled 500s), which would
    otherwise surface in the browser as a misleading "CORS policy" error."""
    if not origin:
        return None
    if origin in _cors_origins or _cors_origin_regex.fullmatch(origin):
        return origin
    return None


def _cors_headers(request: Request) -> dict[str, str]:
    allowed = _allowed_cors_origin(request.headers.get("origin"))
    return {"Access-Control-Allow-Origin": allowed, "Vary": "Origin"} if allowed else {}


@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    """Caching policy — lean on Cloudflare's CDN for anything static/immutable,
    and only defeat caching where the payload is genuinely dynamic.

    - Dynamic API JSON (``/api/*`` except ``/api/assets``): ``no-store`` so live
      data (runs, rankings, models, health) is never served stale from a cache.
    - Everything else (the ``/static`` bundle, the HTML shells, and the
      ``/api/assets`` run-report images): ``no-cache`` — caches *may* store it but
      must revalidate against origin, so a re-run report or a new deploy is
      picked up immediately while unchanged bytes come back as a cheap 304.

    In production the public HTML/JS/CSS is actually served by Cloudflare Pages
    (see scripts/build-pages.sh), which purges its edge on every deploy; the
    ``?v=`` query on the non-content-hashed scripts is the deliberate belt-and-
    braces cache-bust for those. This backend policy governs the API host."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/assets/"):
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = "no-cache"
    return response


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


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Convert any unhandled exception into a JSON 500 that still carries CORS
    headers. Starlette's ServerErrorMiddleware sits outside the CORS middleware,
    so without this the browser reports a bogus "No Access-Control-Allow-Origin"
    error instead of the real failure. Also logs the traceback for debugging."""
    try:
        runtime_paths = get_runtime_paths()
        _append_server_log(
            runtime_paths.logs_dir / "server.log",
            f"unhandled_error method={request.method} path={request.url.path} "
            f"error={exc!r}\n{traceback.format_exc()}",
        )
    except Exception:
        pass
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {exc}"},
        headers=_cors_headers(request),
    )
WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
STATIC_ROOT = WEB_ROOT / "static"

if STATIC_ROOT.exists():
    app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")


def _append_server_log(path: Path, message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    rotate_log_if_needed(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def _log_quiz_json_failure(
    runtime_paths,
    context: str,
    json_text: str,
    error: Exception | None = None,
) -> None:
    log_path = runtime_paths.logs_dir / "quiz_conversion.log"
    snippet = json_text[:2000].replace("\n", "\\n")
    detail = f" error={error}" if error else ""
    _append_server_log(log_path, f"{context} invalid_quiz_json{detail} json_snippet={snippet}")


def _invalid_quiz_json_detail(reason: str) -> str:
    return f"Invalid quiz JSON returned ({reason}; see logs/quiz_conversion.log)"


def _format_conversion_error_detail(error: Exception, limit: int = 300) -> str:
    detail = str(error).replace("\n", " ")
    if len(detail) > limit:
        detail = f"{detail[:limit].rstrip()}..."
    return detail


@app.on_event("startup")
def cleanup_stale_runs() -> None:
    runtime_paths = get_runtime_paths()
    db = connect(runtime_paths.db_path)
    run_ids = db.mark_stale_runs_failed()
    db.close()
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
    if raw_payload.get("type") == "images":
        previews = []
        for image in raw_payload.get("images", []):
            image_path = Path(image.get("path", ""))
            if not image_path.exists():
                continue
            mime = image.get("mime") or "image/png"
            data_url = (
                f"data:{mime};base64,"
                f"{base64.b64encode(image_path.read_bytes()).decode('ascii')}"
            )
            previews.append(
                {
                    "data_url": data_url,
                    "mime": mime,
                    "filename": image_path.name,
                }
            )
        if not previews:
            return None
        return {"type": "images", "images": previews}
    return None


def _client_ip(request: Request) -> str | None:
    """Best-effort client IP, honouring a single proxy hop if present."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    if request.client:
        return request.client.host
    return None


def _actor_detail(user: User | None, client_ip: str | None) -> dict:
    """Forensic actor fields for an audit ``detail`` payload.

    The audit ``ip`` column holds the quota *subject* (the authenticated user's
    id when signed in, otherwise the client IP), so record the real client IP —
    and the user's id/email when present — here so neither is lost.
    """
    detail: dict = {"client_ip": client_ip}
    if user is not None:
        detail["user_id"] = user.id
        if user.email:
            detail["user_email"] = user.email
    return detail


def _record_run_cost(run_id: str, runtime_root: Path) -> None:
    """Compute the run's estimated cost and append an audit entry (best effort)."""
    try:
        runtime_paths = build_runtime_paths(runtime_root)
        db = connect(runtime_paths.db_path)
        rows = db.fetch_results(run_id)
        run = db.fetch_run(run_id)
        ip = db.fetch_ip_for_run(run_id)
        cost_summary = None
        if rows:
            try:
                pricing_map = fetch_openrouter_pricing_map()
                cost_summary = estimate_run_cost(rows, pricing_map)
            except Exception:
                cost_summary = None
        cost_value = None
        if cost_summary and isinstance(cost_summary.get("total"), (int, float)):
            cost_value = float(cost_summary["total"])
        db.insert_audit(
            event="run_completed",
            ip=ip,
            run_id=run_id,
            quiz_id=run.get("quiz_id") if run else None,
            models=run.get("models") if run else None,
            cost_usd=cost_value,
            detail={"status": run.get("status") if run else None},
        )
        # Denormalize the cost onto the run so the admin console can show it per
        # run without a second lookup.
        if run is not None and cost_value is not None:
            merged = dict(run.get("settings") or {})
            merged["cost_usd"] = cost_value
            db.update_run_settings(run_id, merged)
        db.close()
    except Exception:
        # Auditing must never break the run pipeline.
        return


def _reap_stale_runs(runtime_paths, inactivity_seconds: int = 600) -> None:
    """Fail runs whose log has gone quiet — a crashed or hung background task.

    Uses the run log's last-modified time as a liveness signal: active runs
    heartbeat it after every question, so a long silence means it's stuck. The
    window must comfortably exceed a single question's ceiling (120s) plus any
    thread contention when several runs execute at once.
    """
    try:
        db = connect(runtime_paths.db_path)
        try:
            runs = db.fetch_runs()
            now = time.time()
            for run in runs:
                if run.get("status") in ("completed", "failed"):
                    continue
                log_path = runtime_paths.logs_dir / f"{run['run_id']}.log"
                last = None
                try:
                    if log_path.exists():
                        last = log_path.stat().st_mtime
                except OSError:
                    last = None
                if last is None:
                    try:
                        last = datetime.fromisoformat(run["created_at"]).timestamp()
                    except (ValueError, KeyError, TypeError):
                        last = now
                if now - last > inactivity_seconds:
                    db.update_run_status(run["run_id"], "failed")
                    _append_server_log(log_path, "Run marked failed after inactivity timeout.")
        finally:
            db.close()
    except Exception:
        return


def _trigger_rankings_publish(runtime_root: Path) -> None:
    """Re-publish the public rankings snapshot after a run's data changes.

    The public rankings site is a static Cloudflare Pages bundle that bakes
    ``rankings.json`` at build time so it serves entirely from the CDN with no
    per-visit API call. The cost of that is that fresh run data only appears
    once the bundle is rebuilt. Rather than requiring a manual code deploy, we
    ping a Cloudflare Pages *deploy hook* — a data-only rebuild that just
    re-snapshots ``/api/rankings`` — whenever a run finishes. Set the hook URL
    via ``RANKINGS_DEPLOY_HOOK_URL``; unset means the feature is off (e.g. local
    dev, where the page already falls back to the live API).

    Fire-and-forget: any failure here must never fail the run itself, and we log
    only the hook host (never the full URL, which carries a secret token).
    """
    hook_url = os.environ.get("RANKINGS_DEPLOY_HOOK_URL", "").strip()
    if not hook_url:
        return
    log_path = build_runtime_paths(runtime_root).logs_dir / "deploy.log"
    try:
        response = httpx.post(hook_url, timeout=10.0)
        _append_server_log(
            log_path,
            f"rankings_publish status={response.status_code} host={httpx.URL(hook_url).host}",
        )
    except Exception as error:  # noqa: BLE001 - best-effort; must not break a run
        _append_server_log(log_path, f"rankings_publish failed error={error}")


def _run_and_report(
    quiz_path: Path,
    adapters: list,
    run_id: str,
    runtime_root: Path,
    generate_report: bool,
) -> None:
    try:
        run_sync(quiz_path, adapters, run_id, runtime_root)
    except Exception as exc:
        # The runner normally finalizes its own status; if it blew up before it
        # could, the run must NOT be left stuck showing "running" — mark it failed.
        try:
            runtime_paths = build_runtime_paths(runtime_root)
            db = connect(runtime_paths.db_path)
            run = db.fetch_run(run_id)
            if run and run.get("status") not in ("completed", "failed"):
                db.update_run_status(run_id, "failed")
            db.close()
            _append_server_log(
                build_runtime_paths(runtime_root).logs_dir / f"{run_id}.log",
                f"Run failed before completion: {exc}",
            )
        except Exception:
            pass
        return
    if generate_report:
        runtime_paths = build_runtime_paths(runtime_root)
        db = connect(runtime_paths.db_path)
        db.update_run_status(run_id, "reporting")
        db.close()
        try:
            reporter.generate_markdown_report(run_id, runtime_root)
        except Exception:
            db = connect(runtime_paths.db_path)
            db.update_run_status(run_id, "failed")
            db.close()
            raise
        db = connect(runtime_paths.db_path)
        db.update_run_status(run_id, "completed")
        db.close()
    _record_run_cost(run_id, runtime_root)
    _trigger_rankings_publish(runtime_root)


def _run_experiment_and_record(
    experiment: dict,
    adapters: list,
    run_id: str,
    runtime_root: Path,
) -> None:
    """Background task: administer an operational-deception experiment and record
    its cost. The engine finalizes run status itself; this only guards against a
    crash before it could, and never touches the personality rankings."""
    runtime_paths = build_runtime_paths(runtime_root)
    database = connect(runtime_paths.db_path)
    log_path = runtime_paths.logs_dir / f"{run_id}.log"
    try:
        experiments.run_experiment_sync(
            experiment,
            adapters,
            run_id=run_id,
            database=database,
            log_path=log_path,
        )
    except Exception as error:
        try:
            run = database.fetch_run(run_id)
            if run and run.get("status") not in ("completed", "failed"):
                database.update_run_status(run_id, "failed")
        except Exception:
            pass
        _append_server_log(log_path, f"Experiment run failed: {error}")
    finally:
        database.close()
    _record_run_cost(run_id, runtime_root)


def _report_only(run_id: str, runtime_root: Path) -> None:
    runtime_paths = build_runtime_paths(runtime_root)
    db = connect(runtime_paths.db_path)
    db.update_run_status(run_id, "reporting")
    db.close()
    try:
        reporter.generate_markdown_report(run_id, runtime_root)
    except Exception:
        db = connect(runtime_paths.db_path)
        db.update_run_status(run_id, "failed")
        db.close()
        raise
    db = connect(runtime_paths.db_path)
    db.update_run_status(run_id, "completed")
    db.close()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


def require_admin(request: Request) -> None:
    """Gate admin/benchmark actions (single choke point for future user auth).

    Auth-ready placeholder: if ``LLM_POP_QUIZ_ADMIN_TOKEN`` is set, callers must
    send a matching ``X-Admin-Token`` header; when unset (local dev) access is
    open. Replace this with an authenticated admin-user check once accounts land.
    """
    expected = os.environ.get("LLM_POP_QUIZ_ADMIN_TOKEN")
    if not expected:
        return
    provided = request.headers.get("x-admin-token") or ""
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Admin access required")


class BenchmarkRunRequest(BaseModel):
    models: list[str] | None = None
    group: str | None = None
    reps: int = 1
    force: bool = False


# First-party engagement events we accept from the site (allowlist keeps the
# open ingest endpoint from being turned into arbitrary log spam).
ENGAGEMENT_EVENTS = {
    "pageview",
    "view_switched",
    "filter_changed",
    "quiz_started",
    "models_picked",
    "run_started",
    "result_viewed",
}


class EventRequest(BaseModel):
    event: str
    path: str | None = None
    ref: str | None = None
    session: str | None = None
    detail: dict | None = None


@app.get("/api/rankings")
def get_rankings() -> dict:
    """Public rankings payload, computed live from stored benchmark outcomes."""
    runtime_paths = get_runtime_paths()
    conn = connect(runtime_paths.db_path)
    try:
        return benchmarks.build_rankings(conn)
    finally:
        conn.close()


@app.get("/api/experiments/rankings")
def get_experiment_rankings() -> dict:
    """Public deception-experiment payload (kept separate from /api/rankings)."""
    runtime_paths = get_runtime_paths()
    conn = connect(runtime_paths.db_path)
    try:
        return experiments.build_deception_rankings(conn)
    finally:
        conn.close()


@app.get("/api/admin/benchmarks", dependencies=[Depends(require_admin)])
def admin_list_benchmarks() -> dict:
    runtime_paths = get_runtime_paths()
    conn = connect(runtime_paths.db_path)
    try:
        return {"benchmarks": benchmarks.benchmark_coverage(conn)}
    finally:
        conn.close()


@app.post("/api/admin/benchmarks/seed", dependencies=[Depends(require_admin)])
def admin_seed_benchmarks() -> dict:
    runtime_paths = get_runtime_paths()
    conn = connect(runtime_paths.db_path)
    try:
        seeded = benchmarks.seed_benchmarks(conn)
    finally:
        conn.close()
    return {"seeded": seeded}


@app.get("/api/admin/benchmarks/runs", dependencies=[Depends(require_admin)])
def admin_benchmark_runs() -> dict:
    runtime_paths = get_runtime_paths()
    _reap_stale_runs(runtime_paths)
    db = connect(runtime_paths.db_path)
    try:
        ids = benchmarks.benchmark_ids() | experiments.experiment_ids()
        runs = [run for run in db.fetch_runs() if run.get("quiz_id") in ids]
    finally:
        db.close()
    return {"runs": runs}


@app.post("/api/admin/benchmarks/{benchmark_id}/run", dependencies=[Depends(require_admin)])
def admin_run_benchmark(
    benchmark_id: str,
    req: BenchmarkRunRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict:
    bench = benchmarks.get_benchmark(benchmark_id)
    if not bench:
        raise HTTPException(status_code=404, detail="Unknown benchmark")

    use_mocks = os.environ.get("LLM_POP_QUIZ_ENV", "real").lower() == "mock"
    client_ip = _client_ip(request)

    if req.models:
        model_ids = [strip_prefix(model_id) for model_id in req.models]
    elif req.group:
        try:
            model_ids = model_config_loader.model_groups[req.group]
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown model group: {req.group}") from exc
    else:
        raise HTTPException(status_code=400, detail="Select at least one model or group")

    if not model_ids:
        raise HTTPException(status_code=400, detail="No models selected")
    if not use_mocks and not os.environ.get("OPENROUTER_API_KEY"):
        raise HTTPException(status_code=400, detail="OPENROUTER_API_KEY is required")

    runtime_paths = get_runtime_paths()

    # Seed the golden master into the DB + a runtime quiz file so the runner can
    # execute it exactly like any other quiz.
    quiz_json = json.dumps(bench, ensure_ascii=False, indent=2)
    db = connect(runtime_paths.db_path)
    db.upsert_quiz(bench, quiz_json)
    db.close()
    quiz_path = runtime_paths.quizzes_dir / f"{benchmark_id}.json"
    quiz_path.write_text(quiz_json, encoding="utf-8")

    # Skip models that already have a complete result for this benchmark so a
    # rerun only fills the gaps instead of re-billing every model. The rankings
    # aggregate the latest good run per model, so a skipped model still shows.
    # ``force`` overrides this to deliberately re-run everything.
    db = connect(runtime_paths.db_path)
    already_done = benchmarks.models_with_completed_result(db, benchmark_id)
    db.close()
    requested_ids = list(model_ids)
    skipped_models: list[dict] = []
    if not req.force:
        skipped_models = [
            {"model": m, "last_completed": already_done[m]}
            for m in requested_ids
            if m in already_done
        ]
        model_ids = [m for m in requested_ids if m not in already_done]

    if not model_ids:
        return {
            "benchmark_id": benchmark_id,
            "models": [],
            "reps": 0,
            "run_ids": [],
            "skipped": skipped_models,
            "message": "All selected models already have a result — nothing to run. Use Force rerun to run them again.",
        }

    reps = max(1, min(int(req.reps or 1), 5))
    run_ids: list[str] = []
    for rep in range(reps):
        adapters = model_config_loader.create_adapters(model_ids, use_mocks)
        if not adapters:
            raise HTTPException(status_code=400, detail="No available models to run")
        run_id = uuid.uuid4().hex
        db = connect(runtime_paths.db_path)
        db.insert_run(
            run_id=run_id,
            quiz_id=benchmark_id,
            status="queued",
            models=[adapter.id for adapter in adapters],
            settings={
                "benchmark": True,
                "benchmark_id": benchmark_id,
                "rep": rep,
                "skipped_models": skipped_models,
            },
        )
        db.insert_audit(
            event="benchmark_run_created",
            ip=client_ip,
            run_id=run_id,
            quiz_id=benchmark_id,
            models=[adapter.id for adapter in adapters],
            detail={"rep": rep, "reps": reps},
        )
        db.close()
        # Benchmarks skip per-run markdown/charts; rankings render from aggregates.
        background_tasks.add_task(
            _run_and_report, quiz_path, adapters, run_id, runtime_paths.root, False
        )
        run_ids.append(run_id)

    return {
        "benchmark_id": benchmark_id,
        "models": model_ids,
        "reps": reps,
        "run_ids": run_ids,
        "skipped": skipped_models,
    }


@app.get("/api/admin/experiments", dependencies=[Depends(require_admin)])
def admin_list_experiments() -> dict:
    runtime_paths = get_runtime_paths()
    conn = connect(runtime_paths.db_path)
    try:
        return {"experiments": experiments.experiment_coverage(conn)}
    finally:
        conn.close()


@app.get(
    "/api/admin/experiments/{experiment_id}/results",
    dependencies=[Depends(require_admin)],
)
def admin_experiment_results(experiment_id: str) -> dict:
    if not experiments.get_experiment(experiment_id):
        raise HTTPException(status_code=404, detail="Unknown experiment")
    runtime_paths = get_runtime_paths()
    conn = connect(runtime_paths.db_path)
    try:
        aggregate = experiments.aggregate_experiment(conn, experiment_id)
        return aggregate or {"id": experiment_id, "models": {}}
    finally:
        conn.close()


@app.post(
    "/api/admin/experiments/{experiment_id}/run",
    dependencies=[Depends(require_admin)],
)
def admin_run_experiment(
    experiment_id: str,
    req: BenchmarkRunRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict:
    experiment = experiments.get_experiment(experiment_id)
    if not experiment:
        raise HTTPException(status_code=404, detail="Unknown experiment")

    use_mocks = os.environ.get("LLM_POP_QUIZ_ENV", "real").lower() == "mock"
    client_ip = _client_ip(request)

    if req.models:
        model_ids = [strip_prefix(model_id) for model_id in req.models]
    elif req.group:
        try:
            model_ids = model_config_loader.model_groups[req.group]
        except KeyError as exc:
            group_detail = f"Unknown model group: {req.group}"
            raise HTTPException(status_code=400, detail=group_detail) from exc
    else:
        raise HTTPException(status_code=400, detail="Select at least one model or group")

    if not model_ids:
        raise HTTPException(status_code=400, detail="No models selected")
    if not use_mocks and not os.environ.get("OPENROUTER_API_KEY"):
        raise HTTPException(status_code=400, detail="OPENROUTER_API_KEY is required")

    runtime_paths = get_runtime_paths()
    # Register the experiment as a quiz record so runs join to a title. It stays
    # in experiments/ (not benchmarks/), so rankings and the dimensional scorer
    # never see it.
    quiz_stub = {
        "id": experiment_id,
        "title": experiment.get("title", experiment_id),
        "source": experiment.get("source", {}),
    }
    db = connect(runtime_paths.db_path)
    db.upsert_quiz(quiz_stub, json.dumps(experiment, ensure_ascii=False))
    already_done = benchmarks.models_with_completed_result(db, experiment_id)
    db.close()

    requested_ids = list(model_ids)
    skipped_models: list[dict] = []
    if not req.force:
        skipped_models = [
            {"model": m, "last_completed": already_done[m]}
            for m in requested_ids
            if m in already_done
        ]
        model_ids = [m for m in requested_ids if m not in already_done]

    if not model_ids:
        return {
            "experiment_id": experiment_id,
            "models": [],
            "reps": 0,
            "run_ids": [],
            "skipped": skipped_models,
            "message": (
                "All selected models already have a result — nothing to run. "
                "Use Force rerun to run them again."
            ),
        }

    reps = max(1, min(int(req.reps or 1), 5))
    run_ids: list[str] = []
    for rep in range(reps):
        adapters = model_config_loader.create_adapters(model_ids, use_mocks)
        if not adapters:
            raise HTTPException(status_code=400, detail="No available models to run")
        run_id = uuid.uuid4().hex
        db = connect(runtime_paths.db_path)
        db.insert_run(
            run_id=run_id,
            quiz_id=experiment_id,
            status="queued",
            models=[adapter.id for adapter in adapters],
            settings={
                "experiment": True,
                "experiment_id": experiment_id,
                "rep": rep,
                "skipped_models": skipped_models,
            },
        )
        db.insert_audit(
            event="experiment_run_created",
            ip=client_ip,
            run_id=run_id,
            quiz_id=experiment_id,
            models=[adapter.id for adapter in adapters],
            detail={"rep": rep, "reps": reps},
        )
        db.close()
        background_tasks.add_task(
            _run_experiment_and_record, experiment, adapters, run_id, runtime_paths.root
        )
        run_ids.append(run_id)

    return {
        "experiment_id": experiment_id,
        "models": model_ids,
        "reps": reps,
        "run_ids": run_ids,
        "skipped": skipped_models,
    }


@app.post("/api/events")
def track_event(req: EventRequest) -> Response:
    """Ingest a first-party engagement event (anonymous, no PII).

    Open by design (the public site fires these), so it's tightly bounded: only
    allow-listed event names are stored, fields are length-capped, and no IP is
    recorded — uniqueness is by the client-supplied ephemeral session id only.
    """
    name = (req.event or "").strip().lower()
    if name not in ENGAGEMENT_EVENTS:
        # Accept-and-ignore so bots probing the endpoint learn nothing.
        return Response(status_code=204)
    detail = {
        "path": (req.path or "")[:200],
        "ref": (req.ref or "")[:200],
        "session": (req.session or "")[:64],
    }
    if isinstance(req.detail, dict):
        for key, value in list(req.detail.items())[:5]:
            detail[str(key)[:32]] = str(value)[:120]
    try:
        db = connect(get_runtime_paths().db_path)
        try:
            db.insert_audit(event="ev:" + name, ip=None, detail=detail)
        finally:
            db.close()
    except Exception:
        pass  # Analytics must never surface an error to the visitor.
    return Response(status_code=204)


@app.get("/api/admin/stats", dependencies=[Depends(require_admin)])
def admin_stats(days: int = 30) -> dict:
    """Operational + engagement stats for the admin dashboard.

    Cost comes from the ``run_completed`` audit rows (already recorded per run);
    engagement from the ``ev:*`` rows; run/quiz counts from their tables. Tokens
    are summed by joining each windowed run to its stored results.
    """
    days = max(1, min(int(days or 30), 365))
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    day_keys = [(now - timedelta(days=i)).date().isoformat() for i in range(days - 1, -1, -1)]

    db = connect(get_runtime_paths().db_path)
    try:
        runs = db.fetch_runs()
        quizzes = db.fetch_quizzes()
        audit = db.fetch_audit(since)

        def day_of(iso: str) -> str:
            return str(iso or "")[:10]

        runs_series = {k: 0 for k in day_keys}
        cost_series = {k: 0.0 for k in day_keys}
        views_series = {k: 0 for k in day_keys}

        runs_by_status: dict[str, int] = {}
        windowed_runs = []
        for run in runs:
            created = run.get("created_at") or ""
            if created < since:
                continue
            windowed_runs.append(run)
            runs_by_status[run.get("status", "unknown")] = runs_by_status.get(run.get("status", "unknown"), 0) + 1
            d = day_of(created)
            if d in runs_series:
                runs_series[d] += 1

        cost_total = 0.0
        pageviews = 0
        sessions: set[str] = set()
        path_counts: dict[str, int] = {}
        for entry in audit:
            event = entry.get("event") or ""
            created = entry.get("created_at") or ""
            d = day_of(created)
            if event == "run_completed":
                c = entry.get("cost_usd")
                if isinstance(c, (int, float)):
                    cost_total += float(c)
                    if d in cost_series:
                        cost_series[d] += float(c)
            elif event.startswith("ev:"):
                detail = entry.get("detail") or {}
                sess = detail.get("session")
                if sess:
                    sessions.add(sess)
                if event == "ev:pageview":
                    pageviews += 1
                    if d in views_series:
                        views_series[d] += 1
                    path = (detail.get("path") or "").split("?")[0] or "/"
                    path_counts[path] = path_counts.get(path, 0) + 1

        tokens_in = tokens_out = 0
        for run in windowed_runs:
            try:
                for row in db.fetch_results(run["run_id"]):
                    tokens_in += int(row.get("tokens_in") or 0)
                    tokens_out += int(row.get("tokens_out") or 0)
            except Exception:
                continue

        quizzes_in_window = sum(1 for q in quizzes if (q.get("created_at") or "") >= since)
        top_paths = sorted(
            ({"path": p, "views": n} for p, n in path_counts.items()),
            key=lambda x: x["views"],
            reverse=True,
        )[:8]

        return {
            "days": days,
            "generated_at": now.isoformat(),
            "totals": {
                "quizzes": len(quizzes),
                "quizzes_new": quizzes_in_window,
                "runs": len(windowed_runs),
                "runs_by_status": runs_by_status,
                "cost_usd": round(cost_total, 4),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "pageviews": pageviews,
                "sessions": len(sessions),
            },
            "top_paths": top_paths,
            "series": {
                "labels": day_keys,
                "runs": [runs_series[k] for k in day_keys],
                "cost": [round(cost_series[k], 4) for k in day_keys],
                "pageviews": [views_series[k] for k in day_keys],
            },
        }
    finally:
        db.close()


@app.get("/rankings")
def rankings_page() -> FileResponse:
    """Standalone public rankings site (reads /api/rankings)."""
    path = WEB_ROOT / "rankings.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Rankings page not found")
    return FileResponse(path)


@app.get("/ai-deception-experiment")
def deception_experiment_page() -> FileResponse:
    """Public methodology for the operational-deception experiments."""
    path = WEB_ROOT / "ai-deception-experiment.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(path)


@app.get("/ai-deception-rankings")
def deception_rankings_page() -> FileResponse:
    """Public deception rankings visualisation (reads /api/experiments/rankings)."""
    path = WEB_ROOT / "ai-deception-rankings.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(path)


@app.get("/admin")
def admin_page() -> FileResponse:
    """Admin console for running/rerunning benchmarks."""
    path = WEB_ROOT / "admin.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Admin page not found")
    return FileResponse(path)


def _is_rankings_host(request: Request) -> bool:
    """True when served on the public rankings subdomain (rankings.<domain>)."""
    host = (request.headers.get("host") or "").split(":")[0].lower()
    return host.startswith("rankings.")


@app.get("/")
def index(request: Request) -> FileResponse:
    # rankings.<domain> serves the public rankings page at its root; every other
    # host (app.<domain>, localhost, previews) gets the main app.
    page = "rankings.html" if _is_rankings_host(request) else "index.html"
    path = WEB_ROOT / page
    if not path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(path)


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
    db = connect(runtime_paths.db_path)
    quizzes = db.fetch_quizzes()
    db.close()
    # Benchmark quizzes are managed only through the admin console; keep them out
    # of the public quiz library so they can't be selected, reprocessed, or run.
    bench_ids = benchmarks.benchmark_ids()
    quizzes = [q for q in quizzes if q.get("quiz_id") not in bench_ids]
    return {"quizzes": quizzes}


@app.get("/api/quizzes/{quiz_id}")
def get_quiz(quiz_id: str) -> dict:
    runtime_paths = get_runtime_paths()
    db = connect(runtime_paths.db_path)
    try:
        record = db.fetch_quiz_record(quiz_id)
    except ValueError as exc:
        db.close()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.close()
    if not record:
        raise HTTPException(status_code=404, detail="Quiz not found")
    raw_preview = _build_raw_preview(record.get("raw_payload"))
    return {
        "quiz": record["quiz"],
        "quiz_json": record["quiz_json"],
        "quiz_meta": build_quiz_meta(record["quiz"]),
        # Normalize an empty payload to None so the UI doesn't offer "view raw"
        # or re-parse for quizzes whose original input was never captured.
        "raw_payload": record.get("raw_payload") or None,
        "raw_preview": raw_preview,
    }


@app.delete("/api/quizzes/{quiz_id}")
def remove_quiz(quiz_id: str) -> dict:
    runtime_paths = get_runtime_paths()
    # Deleting a benchmark quiz would cascade-delete its official runs and wipe
    # the public rankings, so benchmarks are never deletable via the API.
    if quiz_id in benchmarks.benchmark_ids():
        raise HTTPException(status_code=403, detail="Benchmark quizzes are protected and cannot be deleted.")
    db = connect(runtime_paths.db_path)
    try:
        record = db.fetch_quiz_record(quiz_id)
    except ValueError:
        record = {"raw_payload": None}
    if not record:
        db.close()
        raise HTTPException(status_code=404, detail="Quiz not found")

    run_ids = db.delete_quiz(quiz_id)
    db.close()

    quiz_path = runtime_paths.quizzes_dir / f"{quiz_id}.json"
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
    files: list[UploadFile] | None = File(None),
    model: str | None = Form(None),
) -> dict:
    # A multipart form with an empty file field can yield a single UploadFile
    # with no filename, so filter those out to detect a real upload.
    uploads = [f for f in (files or []) if f and (f.filename or "")]
    if not text and not uploads:
        raise HTTPException(status_code=400, detail="Provide text or image file(s)")

    runtime_paths = get_runtime_paths()

    images: list[tuple[bytes, str]] | None = None
    text_input = text
    raw_payload = {}
    if uploads:
        images = []
        saved_images = []
        for upload in uploads:
            upload_path = await _save_upload(upload, runtime_paths.uploads_dir)
            image_mime = upload.content_type or "image/png"
            images.append((upload_path.read_bytes(), image_mime))
            saved_images.append({"path": str(upload_path), "mime": image_mime})
        text_input = None
        raw_payload = {"type": "images", "images": saved_images}
    elif text_input:
        raw_payload = {"type": "text", "text": text_input}

    try:
        quiz_def = convert_to_quiz(
            text=text_input,
            images=images,
            model=model,
        )
    except Exception as exc:
        _log_quiz_json_failure(runtime_paths, "parse_quiz", str(exc), error=exc)
        detail = _format_conversion_error_detail(exc)
        raise HTTPException(
            status_code=400,
            detail=_invalid_quiz_json_detail(f"conversion error: {detail}"),
        ) from exc
    if not quiz_def or "id" not in quiz_def:
        _log_quiz_json_failure(runtime_paths, "parse_quiz", json.dumps(quiz_def or {}))
        raise HTTPException(
            status_code=400,
            detail=_invalid_quiz_json_detail("missing required id field"),
        )

    quiz_def["id"] = uuid.uuid4().hex
    quiz_json = json.dumps(quiz_def, ensure_ascii=False, indent=2)

    db = connect(runtime_paths.db_path)
    db.upsert_quiz(quiz_def, quiz_json, raw_payload)
    db.close()
    return {
        "quiz": quiz_def,
        "quiz_json": quiz_json,
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
    # Reprocessing overwrites the stored quiz definition via LLM reconversion;
    # never allow that against a committed benchmark's golden master.
    if quiz_id in benchmarks.benchmark_ids():
        raise HTTPException(status_code=403, detail="Benchmark quizzes are protected and cannot be reprocessed.")
    db = connect(runtime_paths.db_path)
    record = db.fetch_quiz_record(quiz_id)
    db.close()
    if not record:
        raise HTTPException(status_code=404, detail="Quiz not found")

    raw_payload = record.get("raw_payload") or {}
    if not raw_payload:
        raise HTTPException(status_code=400, detail="Quiz is missing raw input data")

    image_bytes = None
    image_mime = None
    images = None
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
    elif raw_payload.get("type") == "images":
        images = []
        for image in raw_payload.get("images", []):
            image_path = Path(image.get("path", ""))
            if not image_path.exists():
                raise HTTPException(
                    status_code=500,
                    detail="Stored raw image is missing; cannot reprocess",
                )
            images.append((image_path.read_bytes(), image.get("mime") or "image/png"))
        if not images:
            raise HTTPException(status_code=400, detail="Quiz is missing raw input data")
    else:
        raise HTTPException(status_code=400, detail="Unsupported raw input type")

    try:
        quiz_def = convert_to_quiz(
            text=text_input,
            image_bytes=image_bytes,
            image_mime=image_mime,
            images=images,
            model=model,
        )
    except Exception as exc:
        _log_quiz_json_failure(runtime_paths, "reprocess_quiz", str(exc), error=exc)
        detail = _format_conversion_error_detail(exc)
        raise HTTPException(
            status_code=400,
            detail=_invalid_quiz_json_detail(f"conversion error: {detail}"),
        ) from exc
    if not quiz_def or "id" not in quiz_def:
        _log_quiz_json_failure(runtime_paths, "reprocess_quiz", json.dumps(quiz_def or {}))
        raise HTTPException(
            status_code=400,
            detail=_invalid_quiz_json_detail("missing required id field"),
        )

    quiz_json = json.dumps(quiz_def, ensure_ascii=False, indent=2)
    db = connect(runtime_paths.db_path)
    db.upsert_quiz(quiz_def, quiz_json, raw_payload)
    db.close()
    return {
        "quiz": quiz_def,
        "quiz_json": quiz_json,
        "quiz_meta": build_quiz_meta(quiz_def),
        "raw_payload": raw_payload,
        "raw_preview": _build_raw_preview(raw_payload),
    }


@app.get("/api/auth/config")
def auth_config() -> dict:
    """Public Entra config for the SPA (non-secret; ``enabled: false`` until set)."""
    return frontend_config()


@app.post("/api/runs")
def create_run(
    req: RunRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    user: User | None = Depends(get_current_user),
) -> dict:
    runtime_paths = get_runtime_paths()
    use_mocks = os.environ.get("LLM_POP_QUIZ_ENV", "real").lower() == "mock"
    client_ip = _client_ip(request)
    # Quotas, attribution, and cost tracking all key off a single "subject": the
    # signed-in user's stable id when present, else the client IP. Anonymous
    # callers are unchanged (subject == client IP). The real IP and user
    # identity are preserved in audit ``detail`` via ``_actor_detail``.
    subject = user.id if user else client_ip

    # Benchmark quizzes are the source of the public rankings. They may only be
    # run through the admin benchmark pipeline (which tags runs as official);
    # allowing the open run path to target them would let a visitor inject or
    # overwrite ranking data.
    if req.quiz_id in benchmarks.benchmark_ids():
        raise HTTPException(
            status_code=403,
            detail="This quiz is a protected benchmark and cannot be run from the app.",
        )

    db = connect(runtime_paths.db_path)
    try:
        quiz_json = db.fetch_quiz_json(req.quiz_id)
    except ValueError as exc:
        db.close()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.close()
    if not quiz_json:
        raise HTTPException(status_code=404, detail="Quiz not found")

    quiz_path = runtime_paths.quizzes_dir / f"{req.quiz_id}.json"
    quiz_path.write_text(quiz_json, encoding="utf-8")

    if not req.models and not req.group:
        raise HTTPException(status_code=400, detail="Select at least one model or group")

    # Public app runs authenticate with the app's OWN OpenRouter key so their
    # spend stays isolated from admin/official runs. No fallback to the admin key:
    # a missing app key rejects the run rather than silently billing the wrong key.
    if not use_mocks and not os.environ.get(APP_API_KEY_ENV):
        raise HTTPException(status_code=400, detail=f"{APP_API_KEY_ENV} is required")

    if req.models:
        model_ids = [strip_prefix(model_id) for model_id in req.models]
        adapters = model_config_loader.create_adapters(
            model_ids, use_mocks, api_key_env=APP_API_KEY_ENV
        )
    elif req.group:
        try:
            model_ids = model_config_loader.model_groups[req.group]
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown model group: {req.group}") from exc
        adapters = model_config_loader.create_adapters(
            model_ids, use_mocks, api_key_env=APP_API_KEY_ENV
        )

    if not adapters:
        raise HTTPException(status_code=400, detail="No available models to run")

    quota_model_ids = [adapter.id for adapter in adapters]

    # Enforce lightweight, opt-in usage quotas before spending anything.
    quota_config = load_quota_config()
    if quota_config.enabled:
        pricing_map = None
        if quota_config.max_model_price_per_m and not use_mocks:
            try:
                pricing_map = fetch_openrouter_pricing_map()
            except Exception:
                pricing_map = None
        db = connect(runtime_paths.db_path)
        decision = check_request_quota(
            db, subject, quota_model_ids, pricing_map, quota_config
        )
        if not decision.allowed:
            blocked_detail = {"reason": decision.reason}
            blocked_detail.update(_actor_detail(user, client_ip))
            db.insert_audit(
                event="run_blocked",
                ip=subject,
                quiz_id=req.quiz_id,
                models=quota_model_ids,
                detail=blocked_detail,
            )
            db.close()
            raise HTTPException(status_code=429, detail=decision.reason)
        db.close()

    run_id = uuid.uuid4().hex
    db = connect(runtime_paths.db_path)
    # Tag runs from the open app path as ``public`` so they never feed the
    # public rankings (which only aggregate official benchmark runs).
    run_settings = {"public": True}
    if req.group:
        run_settings["group"] = req.group
    db.insert_run(run_id=run_id,
        quiz_id=req.quiz_id,
        status="queued",
        models=quota_model_ids,
        settings=run_settings,
    )
    created_detail = _actor_detail(user, client_ip)
    if req.group:
        created_detail["group"] = req.group
    db.insert_audit(
        event="run_created",
        ip=subject,
        run_id=run_id,
        quiz_id=req.quiz_id,
        models=quota_model_ids,
        detail=created_detail,
    )
    db.close()
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
    _reap_stale_runs(runtime_paths)
    db = connect(runtime_paths.db_path)
    runs = db.fetch_runs()
    db.close()
    # Official benchmark runs belong to the rankings pipeline (admin console),
    # not the main app's run history. Exclude them from the public list.
    bench_ids = benchmarks.benchmark_ids()
    runs = [r for r in runs if r.get("quiz_id") not in bench_ids]
    return {"runs": runs}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    runtime_paths = get_runtime_paths()
    _reap_stale_runs(runtime_paths)
    db = connect(runtime_paths.db_path)
    run = db.fetch_run(run_id)
    assets = db.fetch_assets(run_id)
    db.close()
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
    db = connect(runtime_paths.db_path)
    run = db.fetch_run(run_id)
    if not run:
        db.close()
        raise HTTPException(status_code=404, detail="Run not found")
    # Benchmark runs feed the rankings and are managed by the admin pipeline;
    # don't let the open report endpoint churn their assets.
    if run.get("quiz_id") in benchmarks.benchmark_ids():
        db.close()
        raise HTTPException(status_code=403, detail="Benchmark runs are protected.")
    if run.get("status") in {"queued", "running", "reporting"}:
        db.close()
        raise HTTPException(status_code=400, detail="Run is still in progress")
    results = db.fetch_results(run_id)
    if not results:
        db.close()
        raise HTTPException(status_code=400, detail="Run has no results to analyze")
    db.delete_assets_for_run(run_id)
    db.close()

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
    db = connect(runtime_paths.db_path)
    rows = db.fetch_results(run_id)
    outcomes = db.fetch_run_outcomes(run_id)
    db.close()
    pricing_map = fetch_openrouter_pricing_map()
    cost_summary = estimate_run_cost(rows, pricing_map) if rows else None
    return {
        "results": rows,
        "outcomes": outcomes,
        "summary": {"cost": cost_summary} if cost_summary else None,
    }


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
def spa_fallback(full_path: str, request: Request) -> FileResponse:
    if full_path.startswith("api/") or full_path.startswith("static/"):
        raise HTTPException(status_code=404, detail="Not found")
    # Deep links resolve to the SPA shell (main app) or the rankings page,
    # depending on the subdomain, so client-side routes survive a refresh.
    page = "rankings.html" if _is_rankings_host(request) else "index.html"
    path = WEB_ROOT / page
    if not path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(path)
