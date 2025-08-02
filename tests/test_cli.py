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

    # Check for timestamped directories in results_mock
    results_mock_dir = tmp_path / "results_mock"
    assert results_mock_dir.exists(), "Expected results_mock directory"
    
    # Check for timestamped run directories
    run_dirs = [d for d in results_mock_dir.iterdir() if d.is_dir()]
    assert len(run_dirs) >= 1, "Expected at least one timestamped run directory"
    
    # Check that the timestamped run directory contains raw subdirectory with json files
    run_dir = run_dirs[0]
    raw_dir = run_dir / "raw"
    assert raw_dir.exists(), f"Expected raw subdirectory in {run_dir}"
    assert any(raw_dir.glob("*.json")), f"Expected json files in {raw_dir}"
