from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    db_path: Path
    assets_dir: Path
    uploads_dir: Path
    quizzes_dir: Path


def build_runtime_paths(root: Path) -> RuntimePaths:
    db_path = root / "db" / "quizbench.sqlite3"
    assets_dir = root / "assets"
    uploads_dir = root / "uploads"
    quizzes_dir = root / "quizzes"

    db_path.parent.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    quizzes_dir.mkdir(parents=True, exist_ok=True)

    return RuntimePaths(
        root=root,
        db_path=db_path,
        assets_dir=assets_dir,
        uploads_dir=uploads_dir,
        quizzes_dir=quizzes_dir,
    )


def get_runtime_paths() -> RuntimePaths:
    env_path = os.environ.get("LLM_POP_QUIZ_RUNTIME_DIR", "").strip()
    if env_path:
        root = Path(env_path)
    else:
        root = Path(__file__).resolve().parents[2] / "runtime-data"

    return build_runtime_paths(root)
