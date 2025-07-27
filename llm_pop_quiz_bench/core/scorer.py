from __future__ import annotations

from collections import Counter
from typing import Iterable, Dict

from .types import QAResult, QuizDefinition


def compute_choice_histogram(results: Iterable[QAResult]) -> Dict[str, int]:
    counter: Counter[str] = Counter()
    for r in results:
        counter[r.choice] += 1
    return dict(counter)


def infer_mostly_letter(hist: Dict[str, int]) -> str:
    return max(hist.items(), key=lambda kv: kv[1])[0]


def infer_mostly_tag(tag_hist: Dict[str, int]) -> str:
    return max(tag_hist.items(), key=lambda kv: kv[1])[0]
