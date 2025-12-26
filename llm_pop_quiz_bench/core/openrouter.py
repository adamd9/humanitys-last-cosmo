from __future__ import annotations

import os
from typing import Any

import httpx

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_PREFIX = "openrouter:"


def strip_prefix(model_id: str) -> str:
    if model_id.startswith(OPENROUTER_PREFIX):
        return model_id[len(OPENROUTER_PREFIX) :]
    return model_id


def fetch_user_models(api_key: str | None = None) -> list[dict[str, Any]]:
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return []
    headers = {"Authorization": f"Bearer {key}"}
    with httpx.Client(base_url=OPENROUTER_BASE_URL, timeout=30) as client:
        resp = client.get("/models/user", headers=headers)
        resp.raise_for_status()
        data = resp.json()
    models = data.get("data")
    if isinstance(models, list):
        return models
    return []


def normalize_models(raw_models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for entry in raw_models:
        model_id = entry.get("id")
        if not model_id:
            continue
        clean_id = strip_prefix(model_id)
        normalized.append(
            {
                "id": clean_id,
                "model": clean_id,
                "name": entry.get("name") or clean_id,
                "description": entry.get("description") or "",
                "context_length": entry.get("context_length"),
                "pricing": entry.get("pricing"),
            }
        )
    return normalized
