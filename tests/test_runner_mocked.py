import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from llm_pop_quiz_bench.adapters.mock_adapter import MockAdapter
from llm_pop_quiz_bench.core.runner import run_quiz


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
    out_dir = tmp_path / "results"
    out_dir.mkdir()
    await run_quiz(quiz_path, [MockAdapter()], "test-run", out_dir)
    # Check for per-run subfolder structure
    run_dir = out_dir / "raw" / "test-run"
    assert run_dir.exists(), "Expected per-run subfolder to exist"
    raw_files = list(run_dir.glob("*.jsonl"))
    assert raw_files, "Expected jsonl files in per-run subfolder"


def test_runner_mocked(tmp_path):
    asyncio.run(_run(tmp_path))
