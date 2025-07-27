from __future__ import annotations

import os
import time

import httpx
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

from .base import ChatResponse


class AnthropicAdapter:
    id = "anthropic"

    def __init__(self, model: str, api_key_env: str) -> None:
        self.model = model
        self.api_key = os.environ.get(api_key_env, "")
        self.client = httpx.AsyncClient(base_url="https://api.anthropic.com/v1")

    async def send(
        self, messages: list[dict[str, str]], params: dict | None = None
    ) -> ChatResponse:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": self.model,
            "messages": messages,
        }
        if params:
            payload.update(params)
        start = time.perf_counter()
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=4)
        ):
            with attempt:
                resp = await self.client.post(
                    "/messages", json=payload, headers=headers, timeout=30
                )
                resp.raise_for_status()
        latency_ms = int((time.perf_counter() - start) * 1000)
        data = resp.json()
        text = data["content"][0]["text"]
        tokens_in = data.get("usage", {}).get("input_tokens")
        tokens_out = data.get("usage", {}).get("output_tokens")
        return ChatResponse(
            text=text, tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency_ms
        )
