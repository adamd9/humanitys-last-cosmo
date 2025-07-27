import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_pop_quiz_bench.cli.main import quiz_run


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

    monkeypatch.setenv("LLM_POP_QUIZ_ENV", "mock")
    monkeypatch.chdir(tmp_path)

    quiz_run(quiz_path)

    raw_dir = tmp_path / "results" / "mock" / "raw"
    assert any(raw_dir.glob("*.jsonl"))
