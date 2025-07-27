import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import asyncio
from pathlib import Path
import yaml

from llm_pop_quiz_bench.core.runner import run_quiz


class MockAdapter:
    id = "mock:adapter"

    async def send(self, messages, params=None):
        return {
            "text": '{"choice":"C","reason":"Fun."}',
            "tokens_in": 10,
            "tokens_out": 5,
            "latency_ms": 50,
        }


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
    raw_files = list((out_dir / "raw").glob("*.jsonl"))
    assert raw_files


def test_runner_mocked(tmp_path):
    asyncio.run(_run(tmp_path))
