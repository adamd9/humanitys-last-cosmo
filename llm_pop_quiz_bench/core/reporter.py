from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple

import pandas as pd

from .store import write_csv


def render_outcomes_table(quiz_title: str, outcomes: Iterable[Tuple[str, str]]) -> str:
    lines = ["| Model | Outcome |", "|-------|---------|"]
    for model_id, outcome in outcomes:
        lines.append(f"| {model_id} | {outcome} |")
    return "\n".join(lines)


def write_summary_csv(path: Path, rows: Iterable[dict]) -> None:
    df = pd.DataFrame(rows)
    write_csv(path, df.to_dict(orient="records"))
