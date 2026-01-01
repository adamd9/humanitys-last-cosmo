from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _rotation_settings() -> tuple[int, int, int]:
    max_bytes = _env_int("LLM_POP_QUIZ_LOG_MAX_BYTES", 5 * 1024 * 1024)
    max_age_hours = _env_int("LLM_POP_QUIZ_LOG_MAX_AGE_HOURS", 24)
    max_files = _env_int("LLM_POP_QUIZ_LOG_MAX_FILES", 5)
    return max_bytes, max_age_hours, max_files


def rotate_log_if_needed(path: Path) -> None:
    max_bytes, max_age_hours, max_files = _rotation_settings()
    if max_bytes <= 0 and max_age_hours <= 0:
        return
    if not path.exists():
        return
    if not path.is_file():
        return

    now = datetime.now(timezone.utc)
    try:
        stat = path.stat()
    except FileNotFoundError:
        return

    size_exceeded = max_bytes > 0 and stat.st_size >= max_bytes
    if max_age_hours > 0:
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        age_exceeded = (now - mtime).total_seconds() >= max_age_hours * 3600
    else:
        age_exceeded = False

    if not size_exceeded and not age_exceeded:
        return

    timestamp = now.strftime("%Y%m%d-%H%M%S")
    rotated_name = f"{path.stem}.{timestamp}{path.suffix}"
    rotated_path = path.with_name(rotated_name)
    rotated_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(rotated_path))

    if max_files <= 0:
        return

    pattern = f"{path.stem}.*{path.suffix}"
    rotated_files = sorted(
        path.parent.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in rotated_files[max_files:]:
        try:
            old.unlink()
        except FileNotFoundError:
            continue
