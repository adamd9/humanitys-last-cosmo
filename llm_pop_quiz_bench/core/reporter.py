from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import yaml

from .scorer import infer_mostly_letter, infer_mostly_tag
from .store import read_jsonl, write_csv


def render_outcomes_table(quiz_title: str, outcomes: Iterable[tuple[str, str]]) -> str:
    lines = ["| Model | Outcome |", "|-------|---------|"]
    for model_id, outcome in outcomes:
        lines.append(f"| {model_id} | {outcome} |")
    return "\n".join(lines)


def write_summary_csv(path: Path, rows: Iterable[dict]) -> None:
    df = pd.DataFrame(rows)
    write_csv(path, df.to_dict(orient="records"))


def load_results(run_id: str, results_dir: Path) -> pd.DataFrame:
    rows: list[dict] = []
    # Look for results in the new per-run subfolder structure
    run_results_dir = results_dir / "raw" / run_id
    if run_results_dir.exists():
        for path in run_results_dir.glob("*.jsonl"):
            parts = path.stem.split(".")
            if len(parts) < 2:
                continue
            quiz_id, model_id = parts
            recs = read_jsonl(path)
            for rec in recs:
                rec.update({"run_id": run_id, "quiz_id": quiz_id, "model_id": model_id})
                rows.append(rec)
    else:
        # Fallback to old structure for backward compatibility
        for path in (results_dir / "raw").glob(f"{run_id}.*.jsonl"):
            parts = path.stem.split(".")
            if len(parts) < 3:
                continue
            _, quiz_id, model_id = parts
            recs = read_jsonl(path)
            for rec in recs:
                rec.update({"run_id": run_id, "quiz_id": quiz_id, "model_id": model_id})
                rows.append(rec)
    return pd.DataFrame(rows)


def render_question_table(df: pd.DataFrame) -> str:
    pivot = df.pivot(index="question_id", columns="model_id", values="choice")
    cols = list(pivot.columns)
    lines = ["| Question | " + " | ".join(cols) + " |"]
    lines.append("|" + "-" * (len(lines[0]) - 2) + "|")
    for qid, row in pivot.iterrows():
        vals = [str(row.get(c, "")) for c in cols]
        lines.append("| " + qid + " | " + " | ".join(vals) + " |")
    return "\n".join(lines)


def compute_model_outcomes(df: pd.DataFrame, quiz_def: dict) -> list[dict[str, str]]:
    lookup = {}
    for q in quiz_def.get("questions", []):
        for opt in q.get("options", []):
            lookup[(q["id"], opt["id"])] = opt

    outcomes = []
    for model_id, g in df.groupby("model_id"):
        letter_hist = g["choice"].value_counts().to_dict()
        tag_hist: dict[str, int] = {}
        score = 0
        for _, row in g.iterrows():
            opt = lookup.get((row["question_id"], row["choice"]))
            if not opt:
                continue
            for t in opt.get("tags", []):
                tag_hist[t] = tag_hist.get(t, 0) + 1
            if "score" in opt and opt["score"] is not None:
                score += opt["score"]
        result = ""
        for rule in quiz_def.get("outcomes", []):
            cond = rule.get("condition", {})
            if "mostly" in cond:
                if letter_hist and infer_mostly_letter(letter_hist) == cond["mostly"]:
                    result = rule["result"]
                    break
            if "mostlyTag" in cond:
                if tag_hist and infer_mostly_tag(tag_hist) == cond["mostlyTag"]:
                    result = rule["result"]
                    break
            if "scoreRange" in cond:
                rng = cond["scoreRange"]
                if rng.get("min", 0) <= score <= rng.get("max", score):
                    result = rule["result"]
                    break
        outcomes.append({"model_id": model_id, "outcome": result})
    return outcomes


def generate_charts(df: pd.DataFrame, out_dir: Path, run_id: str, quiz_id: str) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for model_id, g in df.groupby("model_id"):
        hist = g["choice"].value_counts().sort_index()
        fig, ax = plt.subplots()
        hist.plot.bar(ax=ax)
        ax.set_xlabel("Choice")
        ax.set_ylabel("Count")
        ax.set_title(f"{model_id} choices")
        img_path = out_dir / f"{run_id}.{quiz_id}.{model_id}.png"
        fig.tight_layout()
        fig.savefig(img_path)
        plt.close(fig)
        paths[model_id] = img_path
    return paths


def generate_markdown_report(run_id: str, results_dir: Path) -> None:
    df = load_results(run_id, results_dir)
    if df.empty:
        raise ValueError(f"No results for run {run_id}")
    summary_dir = results_dir / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)
    write_summary_csv(summary_dir / f"{run_id}.csv", df.to_dict(orient="records"))

    for quiz_id, qdf in df.groupby("quiz_id"):
        # Find the quiz file by searching for the quiz ID within files
        quiz_path = None
        quizzes_dir = Path("quizzes")
        for yaml_file in quizzes_dir.glob("*.yaml"):
            try:
                quiz_content = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                if quiz_content.get("id") == quiz_id:
                    quiz_path = yaml_file
                    break
            except (yaml.YAMLError, FileNotFoundError):
                continue
        
        if not quiz_path:
            raise ValueError(f"Quiz file not found for quiz ID: {quiz_id}")
        
        quiz_def = yaml.safe_load(quiz_path.read_text(encoding="utf-8"))
        outcomes = compute_model_outcomes(qdf, quiz_def)
        md_lines = [f"# {quiz_def['title']}", f"Source: {quiz_def['source']['url']}"]
        md_lines.append("\n## Outcomes")
        md_lines.append(
            render_outcomes_table(
                quiz_def["title"], [(o["model_id"], o["outcome"]) for o in outcomes]
            )
        )
        md_lines.append("\n## Choices by Question")
        md_lines.append(render_question_table(qdf))

        chart_paths = generate_charts(qdf, results_dir / "charts", run_id, quiz_id)
        for path in chart_paths.values():
            rel = path.relative_to(summary_dir.parent)
            md_lines.append(f"\n![{path.stem}]({rel.as_posix()})")

        md_content = "\n".join(md_lines)
        md_file = summary_dir / f"{run_id}.{quiz_id}.md"
        md_file.write_text(md_content, encoding="utf-8")
