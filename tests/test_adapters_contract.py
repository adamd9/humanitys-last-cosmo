import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from llm_pop_quiz_bench.adapters.base import ChatAdapter


async def check_adapter(adapter: ChatAdapter):
    msg = [{"role": "user", "content": 'Respond in JSON: {"choice":"A","reason":"Ok"}'}]
    res = await adapter.send(msg, params={"temperature": 0.2})
    assert isinstance(res["text"], str)
    assert "latency_ms" in res


def test_contract_placeholder():
    assert True
