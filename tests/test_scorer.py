import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from llm_pop_quiz_bench.core import scorer


def test_mostly_letter():
    hist = {"A": 3, "B": 1, "C": 0, "D": 0}
    assert scorer.infer_mostly_letter(hist) == "A"


def test_mostly_tag_preference():
    tag_hist = {"fun": 2, "strategic": 1}
    assert scorer.infer_mostly_tag(tag_hist) == "fun"
