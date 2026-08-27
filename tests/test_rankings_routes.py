import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_POP_QUIZ_ENV", "mock")
    monkeypatch.setenv("LLM_POP_QUIZ_RUNTIME_DIR", str(tmp_path))
    from llm_pop_quiz_bench.api.app import app

    return TestClient(app)


def test_public_pages_and_rankings(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    rankings = client.get("/rankings")
    assert rankings.status_code == 200
    # The rankings page is client-rendered, so assert on stable shell markers
    # rather than a heading that now lives in JS.
    assert "AI Personality Benchmark" in rankings.text
    assert "rankings.js" in rankings.text

    assert client.get("/admin").status_code == 200

    data = client.get("/api/rankings").json()
    ids = {b["id"] for b in data["benchmarks"]}
    assert {"big_five_ipip50", "mbti_oejts", "sd3_short_dark_triad"} <= ids


def test_admin_requires_token_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_POP_QUIZ_ADMIN_TOKEN", "secret")
    client = _client(monkeypatch, tmp_path)

    assert client.get("/api/admin/benchmarks").status_code == 403
    ok = client.get("/api/admin/benchmarks", headers={"X-Admin-Token": "secret"})
    assert ok.status_code == 200
    assert len(ok.json()["benchmarks"]) == 3
