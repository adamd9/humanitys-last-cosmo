from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from .types import QAResult


def compute_choice_histogram(results: Iterable[QAResult]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for r in results:
        counter[r.choice] += 1
    return dict(counter)


def infer_mostly_letter(hist: dict[str, int]) -> str:
    return max(hist.items(), key=lambda kv: kv[1])[0]


def infer_mostly_tag(tag_hist: dict[str, int]) -> str:
    return max(tag_hist.items(), key=lambda kv: kv[1])[0]
