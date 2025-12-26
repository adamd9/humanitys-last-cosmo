import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from llm_pop_quiz_bench.adapters.mock_adapter import MockAdapter
from llm_pop_quiz_bench.core.runner import run_quiz
from llm_pop_quiz_bench.core.sqlite_store import connect, fetch_results


async def _run(tmp_path: Path):
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
    with open(quiz_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(quiz, f)
    run_id = "test-run"
    runtime_dir = tmp_path / "runtime-data"
    await run_quiz(quiz_path, [MockAdapter()], run_id, runtime_dir)

    # Check that results are stored in SQLite
    db_path = runtime_dir / "db" / "quizbench.sqlite3"
    assert db_path.exists(), f"Expected database at {db_path}"

    conn = connect(db_path)
    rows = fetch_results(conn, run_id)
    conn.close()

    assert rows, "Expected at least one result row"
    assert rows[0]["run_id"] == run_id
    assert "mock" in rows[0]["model_id"]


def test_runner_mocked(tmp_path):
    asyncio.run(_run(tmp_path))
