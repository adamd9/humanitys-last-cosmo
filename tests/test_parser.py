import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import json
from llm_pop_quiz_bench.core import utils


def test_parse_strict_json_ok():
    txt = '{"choice":"B","reason":"Because it fits."}'
    data = utils.parse_choice_json(txt)
    assert data["choice"] == "B"


def test_parse_with_extra_text():
    txt = "Sure! Here you go:\n{\"choice\":\"A\",\"reason\":\"Why not.\"}\nThanks!"
    data = utils.parse_choice_json(txt)
    assert data["choice"] == "A"


def test_parse_malformed_json_returns_none():
    txt = "No JSON here"
    assert utils.parse_choice_json(txt) is None
