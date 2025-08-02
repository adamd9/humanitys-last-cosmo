from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

try:
    from pandasai import SmartDataframe  # type: ignore
    from pandasai.llm.fake import FakeLLM  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    SmartDataframe = None  # type: ignore
    FakeLLM = None  # type: ignore


def _detect_quiz_type(quiz_def: dict) -> str:
    for rule in quiz_def.get("outcomes", []):
        cond = rule.get("condition", {})
        if any(k in cond for k in ("mostly", "mostlyTag")):
            return "personality"
    return "generic"


def generate_visualizations(
    df: pd.DataFrame,
    outcomes: list[dict[str, str]],
    quiz_def: dict,
    out_dir: Path,
    run_id: str,
    quiz_id: str,
) -> dict[str, Path]:
    """Generate charts using PandasAI when available.

    Returns a mapping of chart labels to file paths.
    """

    if SmartDataframe is None or FakeLLM is None:  # pragma: no cover - runtime guard
        raise RuntimeError("pandasai is not installed")

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    quiz_type = _detect_quiz_type(quiz_def)

    if quiz_type == "personality" and outcomes:
        data = pd.DataFrame(outcomes)
        sdf = SmartDataframe(data, config={"llm": FakeLLM()})
        sdf.chat("Plot a bar chart showing the count of each outcome.")
        fig = plt.gcf()
        img_path = out_dir / f"{run_id}.{quiz_id}.outcomes.png"
        fig.savefig(img_path)
        plt.close(fig)
        paths["outcomes"] = img_path
    else:
        sdf = SmartDataframe(df, config={"llm": FakeLLM()})
        sdf.chat("Plot the distribution of choices for each model.")
        fig = plt.gcf()
        img_path = out_dir / f"{run_id}.{quiz_id}.choices.png"
        fig.savefig(img_path)
        plt.close(fig)
        paths["choices"] = img_path

    return paths
