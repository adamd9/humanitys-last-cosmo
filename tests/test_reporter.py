import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from llm_pop_quiz_bench.core import reporter


def test_markdown_table_renders():
    md = reporter.render_outcomes_table(
        quiz_title="Sample Quiz",
        outcomes=[("openai:gpt-4o", "Leonardo"), ("anthropic:claude-3-5-sonnet", "Donatello")],
    )
    assert "openai:gpt-4o" in md
