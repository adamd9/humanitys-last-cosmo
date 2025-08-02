from __future__ import annotations

import os
import time
from typing import Union

import httpx
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

from .base import ChatResponse


class GoogleAdapter:
    id = "google"

    def __init__(self, model: str, api_key_env: str) -> None:
        self.model = model
        self.api_key = os.environ.get(api_key_env, "")
        self.client = httpx.AsyncClient(base_url="https://generativelanguage.googleapis.com/v1beta")

    async def send(
        self, messages: list[dict[str, str]], params: Union[dict, None] = None
    ) -> ChatResponse:
        # Convert messages to Google's format
        # Google expects a single "contents" array with parts
        contents = []
        for msg in messages:
            if msg["role"] == "user":
                contents.append({
                    "parts": [{"text": msg["content"]}],
                    "role": "user"
                })
            elif msg["role"] == "system":
                # Google doesn't have system role, prepend to first user message
                if contents and contents[-1]["role"] == "user":
                    contents[-1]["parts"][0]["text"] = msg["content"] + "\n\n" + contents[-1]["parts"][0]["text"]
                else:
                    contents.append({
                        "parts": [{"text": msg["content"]}],
                        "role": "user"
                    })

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": params.get("temperature", 0.7) if params else 0.7,
                "maxOutputTokens": 1024,
                "candidateCount": 1
            }
        }

        url = f"/models/{self.model}:generateContent"
        headers = {"Content-Type": "application/json"}
        
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10)
        ):
            with attempt:
                start_time = time.perf_counter()
                response = await self.client.post(
                    url,
                    json=payload,
                    headers=headers,
                    params={"key": self.api_key},
                    timeout=30.0,
                )
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                response.raise_for_status()
                data = response.json()

                # Extract response text
                if "candidates" in data and data["candidates"]:
                    candidate = data["candidates"][0]
                    if "content" in candidate and "parts" in candidate["content"]:
                        text = candidate["content"]["parts"][0].get("text", "")
                    else:
                        text = ""
                else:
                    text = ""

                # Extract token usage if available
                usage = data.get("usageMetadata", {})
                tokens_in = usage.get("promptTokenCount")
                tokens_out = usage.get("candidatesTokenCount")

                return ChatResponse(
                    text=text,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency_ms,
                )
