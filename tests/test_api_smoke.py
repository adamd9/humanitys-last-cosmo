import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_pop_quiz_bench.api.app import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_POP_QUIZ_RUNTIME_DIR", str(tmp_path / "runtime-data"))
    return TestClient(app)


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_startup_cleanup_failure_does_not_prevent_boot(monkeypatch, tmp_path):
    import importlib

    api_app = importlib.import_module("llm_pop_quiz_bench.api.app")

    class FailingDatabase:
        closed = False

        def mark_stale_runs_failed(self):
            raise RuntimeError("database is read-only")

        def close(self):
            self.closed = True

    database = FailingDatabase()
    monkeypatch.setenv("LLM_POP_QUIZ_RUNTIME_DIR", str(tmp_path / "runtime-data"))
    monkeypatch.setattr(api_app, "connect", lambda _: database)

    api_app.cleanup_stale_runs()

    assert database.closed is True
    server_log = tmp_path / "runtime-data" / "logs" / "server.log"
    assert "startup stale-run cleanup skipped" in server_log.read_text()


def test_models(client):
    resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data
    assert "groups" in data


def test_subdomain_host_routing(client):
    # Default (app) host serves the main app SPA shell.
    app_root = client.get("/")
    assert app_root.status_code == 200
    assert "/static/app.js" in app_root.text
    # rankings.<domain> serves the rankings page at its root.
    rankings_root = client.get("/", headers={"Host": "rankings.thelastquiz.net"})
    assert rankings_root.status_code == 200
    assert "/static/rankings.js" in rankings_root.text
    # Deep links resolve to the right shell per host (host-aware SPA fallback).
    app_deep = client.get("/create-run", headers={"Host": "app.thelastquiz.net"})
    assert app_deep.status_code == 200 and "/static/app.js" in app_deep.text
    rankings_deep = client.get("/anything", headers={"Host": "rankings.thelastquiz.net"})
    assert rankings_deep.status_code == 200 and "/static/rankings.js" in rankings_deep.text


def test_parse_quiz_text(client, monkeypatch):
    import importlib

    api_app = importlib.import_module("llm_pop_quiz_bench.api.app")

    quiz_def = {
        "id": "mock-quiz",
        "title": "Mock Quiz",
        "source": {"publication": "X", "url": "https://x"},
        "questions": [
            {
                "id": "Q1",
                "text": "Pick one:",
                "options": [
                    {"id": "A", "text": "A"},
                    {"id": "B", "text": "B"},
                    {"id": "C", "text": "C"},
                ],
            }
        ],
        "outcomes": [],
    }

    monkeypatch.setattr(api_app, "convert_to_quiz", lambda **_: quiz_def)
    resp = client.post("/api/quizzes/parse", data={"text": "mock"})
    assert resp.status_code == 200
    assert resp.json()["quiz"]["id"]


def test_create_run_returns_id(client, monkeypatch):
    import importlib

    api_app = importlib.import_module("llm_pop_quiz_bench.api.app")

    quiz_def = {
        "id": "mock-quiz",
        "title": "Mock Quiz",
        "source": {"publication": "X", "url": "https://x"},
        "questions": [
            {
                "id": "Q1",
                "text": "Pick one:",
                "options": [
                    {"id": "A", "text": "A"},
                    {"id": "B", "text": "B"},
                    {"id": "C", "text": "C"},
                ],
            }
        ],
        "outcomes": [],
    }

    monkeypatch.setenv("LLM_POP_QUIZ_ENV", "mock")
    monkeypatch.setattr(api_app, "convert_to_quiz", lambda **_: quiz_def)
    monkeypatch.setattr(api_app, "_run_and_report", lambda *args, **kwargs: None)

    resp = client.post("/api/quizzes/parse", data={"text": "mock"})
    assert resp.status_code == 200
    quiz_id = resp.json()["quiz"]["id"]

    run_resp = client.post("/api/runs", json={"quiz_id": quiz_id, "models": ["openai/gpt-4o"]})
    assert run_resp.status_code == 200
    assert "run_id" in run_resp.json()


def test_reprocess_quiz_from_raw(client, monkeypatch):
    import importlib

    api_app = importlib.import_module("llm_pop_quiz_bench.api.app")

    base_quiz_def = {
        "id": "mock-quiz",
        "title": "Mock Quiz",
        "source": {"publication": "X", "url": "https://x"},
        "questions": [
            {
                "id": "Q1",
                "text": "Pick one:",
                "options": [
                    {"id": "A", "text": "A"},
                    {"id": "B", "text": "B"},
                ],
            }
        ],
        "outcomes": [],
    }

    monkeypatch.setattr(api_app, "convert_to_quiz", lambda **kwargs: base_quiz_def)
    resp = client.post("/api/quizzes/parse", data={"text": "initial raw"})
    assert resp.status_code == 200
    parsed = resp.json()
    quiz_id = parsed["quiz"]["id"]
    assert parsed["raw_preview"]["text"] == "initial raw"

    def reprocess_convert_to_quiz(**kwargs):
        assert kwargs.get("text") == "initial raw"
        updated = dict(base_quiz_def)
        updated["title"] = "Reprocessed Title"
        return updated

    monkeypatch.setattr(api_app, "convert_to_quiz", reprocess_convert_to_quiz)
    reprocess_resp = client.post(f"/api/quizzes/{quiz_id}/reprocess")
    assert reprocess_resp.status_code == 200
    data = reprocess_resp.json()
    assert data["quiz"]["title"] == "Reprocessed Title"
    assert data["raw_payload"]["type"] == "text"
    assert data["raw_preview"]["text"] == "initial raw"


def test_delete_quiz_removes_runs_and_assets(client, monkeypatch):
    import importlib

    from llm_pop_quiz_bench.core.runtime_data import get_runtime_paths
    from llm_pop_quiz_bench.core.db_factory import connect

    api_app = importlib.import_module("llm_pop_quiz_bench.api.app")

    quiz_def = {
        "id": "mock-quiz",
        "title": "Mock Quiz",
        "source": {"publication": "X", "url": "https://x"},
        "questions": [
            {
                "id": "Q1",
                "text": "Pick one:",
                "options": [{"id": "A", "text": "A"}],
            }
        ],
        "outcomes": [],
    }

    monkeypatch.setattr(api_app, "convert_to_quiz", lambda **_: quiz_def)
    resp = client.post("/api/quizzes/parse", data={"text": "mock"})
    assert resp.status_code == 200
    quiz_id = resp.json()["quiz"]["id"]

    runtime_paths = get_runtime_paths()
    db = connect(runtime_paths.db_path)
    db.insert_run(run_id="run-123", quiz_id=quiz_id, status="running", models=["m"])
    run_assets_dir = runtime_paths.assets_dir / "run-123"
    run_assets_dir.mkdir(parents=True, exist_ok=True)
    asset_path = run_assets_dir / "report.txt"
    asset_path.write_text("sample", encoding="utf-8")
    db.insert_asset("run-123", "report", asset_path)
    db.close()

    delete_resp = client.delete(f"/api/quizzes/{quiz_id}")
    assert delete_resp.status_code == 200
    data = delete_resp.json()
    assert data["quiz_id"] == quiz_id
    assert data["runs_removed"] == 1
    assert not run_assets_dir.exists()

    db = connect(runtime_paths.db_path)
    # For disk/mongo storage, we need to use the db interface, not SQL directly
    runs = db.fetch_runs()
    run_count = len([r for r in runs if r["quiz_id"] == quiz_id])
    quizzes = db.fetch_quizzes()
    quiz_count = len([q for q in quizzes if q["quiz_id"] == quiz_id])
    db.close()

    assert run_count == 0
    assert quiz_count == 0

    missing = client.get(f"/api/quizzes/{quiz_id}")
    assert missing.status_code == 404
