from __future__ import annotations

import os
import time

import httpx
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential
from typing import Union

from .base import ChatResponse


class GrokAdapter:
    id = "grok"

    def __init__(self, model: str, api_key_env: str) -> None:
        self.model = model
        self.api_key = os.environ.get(api_key_env, "")
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        if proxy:
            self.client = httpx.AsyncClient(
                base_url="https://api.x.ai/v1", proxy=proxy
            )
        else:
            self.client = httpx.AsyncClient(base_url="https://api.x.ai/v1")

    async def send(
        self, messages: list[dict[str, str]], params: Union[dict, None] = None
    ) -> ChatResponse:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 256,
        }
        if params:
            payload.update(params)

        start = time.perf_counter()
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
        ):
            with attempt:
                resp = await self.client.post("/chat/completions", json=payload, headers=headers, timeout=30)
                resp.raise_for_status()
        
        latency_ms = int((time.perf_counter() - start) * 1000)
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        tokens_in = data.get("usage", {}).get("prompt_tokens")
        tokens_out = data.get("usage", {}).get("completion_tokens")
        
        return ChatResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms
        )
