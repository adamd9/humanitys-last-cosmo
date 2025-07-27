from __future__ import annotations

from typing import Protocol, TypedDict


class ChatResponse(TypedDict, total=False):
    text: str
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int


class ChatAdapter(Protocol):
    id: str

    async def send(
        self, messages: list[dict[str, str]], params: dict | None = None
    ) -> ChatResponse: ...
