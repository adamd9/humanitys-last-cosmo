import pandas as pd

from llm_pop_quiz_bench.core import visualizer


def _patch_pandasai(monkeypatch):
    class DummySDF:
        def __init__(self, df, config=None):
            self.df = df

        def chat(self, prompt):  # pragma: no cover - simple stub
            import matplotlib.pyplot as plt
            plt.figure()
            plt.bar([1, 2], [3, 4])

    monkeypatch.setattr(visualizer, "SmartDataframe", DummySDF)
    monkeypatch.setattr(visualizer, "FakeLLM", lambda: object())


def test_generate_visualizations_personality(tmp_path, monkeypatch):
    _patch_pandasai(monkeypatch)
    df = pd.DataFrame([
        {"model_id": "m1", "question_id": "Q1", "choice": "A"},
        {"model_id": "m1", "question_id": "Q2", "choice": "A"},
    ])
    quiz_def = {
        "questions": [
            {"id": "Q1", "options": [{"id": "A", "text": ""}]},
            {"id": "Q2", "options": [{"id": "A", "text": ""}]},
        ],
        "outcomes": [{"condition": {"mostly": "A"}, "result": "Alpha"}],
    }
    outcomes = [{"model_id": "m1", "outcome": "Alpha"}]
    paths = visualizer.generate_visualizations(
        df, outcomes, quiz_def, tmp_path, "run", "quiz"
    )
    path = paths.get("outcomes")
    assert path is not None
    assert path.exists()
