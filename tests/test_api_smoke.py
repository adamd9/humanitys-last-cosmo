import sys
from pathlib import Path

import pytest
import yaml
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


def test_models(client):
    resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data
    assert "groups" in data


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

    monkeypatch.setattr(api_app, "convert_to_yaml", lambda **_: yaml.safe_dump(quiz_def))
    resp = client.post("/api/quizzes/parse", data={"text": "mock"})
    assert resp.status_code == 200
    assert resp.json()["quiz"]["id"] == "mock-quiz"


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
    monkeypatch.setattr(api_app, "convert_to_yaml", lambda **_: yaml.safe_dump(quiz_def))
    monkeypatch.setattr(api_app, "_run_and_report", lambda *args, **kwargs: None)

    resp = client.post("/api/quizzes/parse", data={"text": "mock"})
    assert resp.status_code == 200

    run_resp = client.post("/api/runs", json={"quiz_id": "mock-quiz", "models": ["openai:gpt-4o"]})
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

    monkeypatch.setattr(api_app, "convert_to_yaml", lambda **kwargs: yaml.safe_dump(base_quiz_def))
    resp = client.post("/api/quizzes/parse", data={"text": "initial raw"})
    assert resp.status_code == 200

    def reprocess_convert_to_yaml(**kwargs):
        assert kwargs.get("text") == "initial raw"
        updated = dict(base_quiz_def)
        updated["title"] = "Reprocessed Title"
        return yaml.safe_dump(updated)

    monkeypatch.setattr(api_app, "convert_to_yaml", reprocess_convert_to_yaml)
    reprocess_resp = client.post("/api/quizzes/mock-quiz/reprocess")
    assert reprocess_resp.status_code == 200
    data = reprocess_resp.json()
    assert data["quiz"]["title"] == "Reprocessed Title"
    assert data["raw_payload"]["type"] == "text"
