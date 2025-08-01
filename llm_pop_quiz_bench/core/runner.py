from __future__ import annotations

import asyncio
import time
from pathlib import Path

import json
import yaml

from ..adapters.base import ChatAdapter
from .prompt import PromptContext, render_prompt
from .types import QAResult
from .utils import parse_choice_json


async def run_quiz(
    quiz_path: Path, adapters: list[ChatAdapter], run_id: str, results_dir: Path
) -> None:
    with open(quiz_path, encoding="utf-8") as f:
        quiz = yaml.safe_load(f)

    questions = quiz["questions"]
    all_results: dict[str, list[dict]] = {}

    for adapter in adapters:
        model_records: list[dict] = []
        for idx, q in enumerate(questions, start=1):
            ctx = PromptContext(
                quiz_title=quiz["title"],
                q_num=idx,
                q_total=len(questions),
                question_text=q["text"],
                options=[opt["text"] for opt in q["options"]],
            )
            prompt = render_prompt(ctx)
            messages = [{"role": "user", "content": prompt}]
            start = time.perf_counter()
            resp = await adapter.send(messages, params={"temperature": 0.2})
            latency_ms = int((time.perf_counter() - start) * 1000)
            data = parse_choice_json(resp["text"])
            if not data:
                data = {"choice": "", "reason": "", "refused": True}
            rec = QAResult(
                question_id=q["id"],
                choice=data.get("choice", ""),
                reason=data.get("reason", ""),
                refused=data.get("refused", False),
                latency_ms=latency_ms,
                tokens_in=resp.get("tokens_in"),
                tokens_out=resp.get("tokens_out"),
            )
            model_records.append(rec.__dict__)
        all_results[adapter.id] = model_records

    run_results_dir = results_dir / "raw" / run_id
    run_results_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_results_dir / f"{quiz['id']}.json"
    payload = {"run_id": run_id, "quiz_id": quiz["id"], "results": all_results}
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def run_sync(*args, **kwargs) -> None:
    asyncio.run(run_quiz(*args, **kwargs))
