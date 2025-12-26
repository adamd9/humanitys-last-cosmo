import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_pop_quiz_bench.cli.main import quiz_run
from llm_pop_quiz_bench.core.sqlite_store import connect, fetch_results


def test_cli_mock_results_dir(tmp_path, monkeypatch):
    quiz = {
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
    }
    quiz_path = tmp_path / "quiz.yaml"
    quiz_path.write_text(yaml.safe_dump(quiz), encoding="utf-8")

    runtime_dir = tmp_path / "runtime-data"
    monkeypatch.setenv("LLM_POP_QUIZ_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("LLM_POP_QUIZ_ENV", "mock")
    monkeypatch.chdir(tmp_path)

    quiz_run(quiz_path, models="openai/gpt-4o")

    db_path = runtime_dir / "db" / "quizbench.sqlite3"
    assert db_path.exists(), "Expected runtime SQLite database"

    conn = connect(db_path)
    row = conn.execute(
        "SELECT run_id FROM runs ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    assert row is not None, "Expected a run recorded in SQLite"
    run_id = row["run_id"]
    rows = fetch_results(conn, run_id)
    conn.close()

    assert rows, "Expected results rows in SQLite"
