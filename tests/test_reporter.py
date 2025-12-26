import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pandas as pd

from llm_pop_quiz_bench.core import reporter


def test_markdown_table_renders():
    md = reporter.render_outcomes_table(
        quiz_title="Sample Quiz",
        outcomes=[("openrouter:openai/gpt-4o", "Leonardo"), ("openrouter:anthropic/claude-3.5-sonnet", "Donatello")],
    )
    assert "openrouter:openai/gpt-4o" in md


def test_ai_reasoning_includes_answer_text():
    df = pd.DataFrame(
        [
            {
                "question_id": "Q1",
                "model_id": "openai",
                "choice": "B",
                "reason": "Because it's refreshing",
                "additional_thoughts": "",
            }
        ]
    )
    quiz_def = {
        "questions": [
            {
                "id": "Q1",
                "text": "Your drink of choice:",
                "options": [
                    {"id": "A", "text": "Coffee"},
                    {"id": "B", "text": "Water with lemon"},
                ],
            }
        ]
    }
    md = reporter.render_ai_reasoning_section(df, quiz_def)
    assert "B: Water with lemon" in md
