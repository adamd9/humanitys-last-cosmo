"""Configuration loader for LLM tasks (scoring, summaries, conversions)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

DEFAULT_TASKS: dict[str, dict[str, str]] = {
    "quiz_scoring": {
        "model": "gpt-4o",
        "api_key_env": "OPENAI_API_KEY",
    },
    "summary_generation": {
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
    "quiz_conversion": {
        "model": "gpt-4o",
        "api_key_env": "OPENAI_API_KEY",
    },
}


class LLMTaskConfigLoader:
    """Loads task-specific LLM settings from config/llm_tasks.yaml."""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        if config_path is None:
            project_root = Path(__file__).parent.parent.parent
            config_path = project_root / "config" / "llm_tasks.yaml"
        self.config_path = config_path
        self._config: dict[str, Any] | None = None

    def _load_config(self) -> None:
        if self._config is not None:
            return
        if not self.config_path.exists():
            self._config = {}
            return
        with self.config_path.open("r", encoding="utf-8") as handle:
            self._config = yaml.safe_load(handle) or {}

    def get_task(self, task_name: str) -> dict[str, str]:
        """Return merged task settings with defaults applied."""
        self._load_config()
        base = DEFAULT_TASKS.get(task_name, {})
        user_tasks = (self._config or {}).get("llm_tasks", {})
        user_task = user_tasks.get(task_name, {}) if isinstance(user_tasks, dict) else {}
        merged = dict(base)
        if isinstance(user_task, dict):
            merged.update({k: v for k, v in user_task.items() if v})
        return merged


llm_task_config = LLMTaskConfigLoader()
