from __future__ import annotations

import os
import time
from typing import List, Dict

import httpx
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

from .base import ChatAdapter, ChatResponse


class OpenAIAdapter:
    id = "openai"

    def __init__(self, model: str, api_key_env: str) -> None:
        self.model = model
        self.api_key = os.environ.get(api_key_env, "")
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        self.client = httpx.AsyncClient(
            base_url="https://api.openai.com/v1", proxies=proxy if proxy else None
        )

    async def send(
        self, messages: List[Dict[str, str]], params: Dict | None = None
    ) -> ChatResponse:
        headers = {"Authorization": f"Bearer {self.api_key}"}
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
                    "/chat/completions", json=payload, headers=headers, timeout=30
                )
                resp.raise_for_status()
        latency_ms = int((time.perf_counter() - start) * 1000)
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        tokens_in = data.get("usage", {}).get("prompt_tokens")
        tokens_out = data.get("usage", {}).get("completion_tokens")
        return ChatResponse(
            text=text, tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency_ms
        )
