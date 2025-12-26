from __future__ import annotations

import os
import time
from typing import Union

import httpx
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

from .base import ChatResponse


class OpenRouterAdapter:
    id = "openrouter"

    def __init__(self, model: str, api_key_env: str) -> None:
        self.model = model
        self.api_key = os.environ.get(api_key_env, "")
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        if proxy:
            self.client = httpx.AsyncClient(
                base_url="https://openrouter.ai/api/v1", proxy=proxy
            )
        else:
            self.client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1")

    async def send(
        self, messages: list[dict[str, str]], params: Union[dict, None] = None
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
                try:
                    resp = await self.client.post(
                        "/chat/completions", json=payload, headers=headers, timeout=30
                    )
                    resp.raise_for_status()
                except httpx.HTTPStatusError as e:
                    raise Exception(self._format_api_error(e.response)) from e
                except Exception as e:
                    raise Exception(
                        f"OpenRouter API request failed for model '{self.model}': {str(e)}"
                    ) from e
        latency_ms = int((time.perf_counter() - start) * 1000)
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        tokens_in = data.get("usage", {}).get("prompt_tokens")
        tokens_out = data.get("usage", {}).get("completion_tokens")
        return ChatResponse(
            text=text, tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency_ms
        )

    def _format_api_error(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        error = payload.get("error", {})
        message = error.get("message") or payload.get("message") or response.text
        status = response.status_code
        if status == 401:
            return "❌ Authentication failed for OpenRouter API. Check OPENROUTER_API_KEY."
        if status == 404 and "model" in str(message).lower():
            return f"❌ OpenRouter model '{self.model}' not found or not accessible."
        return f"❌ OpenRouter API error ({status}): {message}"
