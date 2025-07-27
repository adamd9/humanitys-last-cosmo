from __future__ import annotations

import time

from .base import ChatResponse


class MockAdapter:
    """Simple adapter that returns canned responses for testing."""

    def __init__(self, model: str = "mock") -> None:
        self.id = f"mock:{model}"

    async def send(
        self, messages: list[dict[str, str]], params: dict | None = None
    ) -> ChatResponse:
        start = time.perf_counter()
        latency_ms = int((time.perf_counter() - start) * 1000)
        return ChatResponse(
            text='{"choice":"C","reason":"Mock response."}',
            tokens_in=0,
            tokens_out=0,
            latency_ms=latency_ms,
        )
