import asyncio
import json
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
    # Simulate the new timestamped directory structure that CLI creates
    from datetime import datetime
    run_id = "test-run"
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir_name = f"{timestamp}_{run_id[:8]}"
    
    results_base_dir = tmp_path / "results"
    timestamped_dir = results_base_dir / run_dir_name
    
    await run_quiz(quiz_path, [MockAdapter()], run_id, timestamped_dir)
    
    # Check that results are stored in timestamped directory structure
    assert timestamped_dir.exists(), f"Expected timestamped directory {timestamped_dir}"
    
    raw_dir = timestamped_dir / "raw"
    assert raw_dir.exists(), f"Expected raw subdirectory in {timestamped_dir}"
    
    json_files = list(raw_dir.glob("*.json"))
    assert len(json_files) == 1, f"Expected exactly one JSON file, found {len(json_files)}"
    
    # Validate JSON content structure
    json_file = json_files[0]
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert "run_id" in data
    assert "quiz_id" in data
    assert "results" in data
    # Check for mock adapter results (ID format is "mock:mock")
    mock_key = next((k for k in data["results"].keys() if "mock" in k), None)
    assert mock_key is not None, f"Expected mock adapter results, found keys: {list(data['results'].keys())}"
    assert len(data["results"][mock_key]) == 1  # One question in this test


def test_runner_mocked(tmp_path):
    asyncio.run(_run(tmp_path))
