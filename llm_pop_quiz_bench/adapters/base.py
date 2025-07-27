from __future__ import annotations

from typing import Protocol, TypedDict, List, Dict


class ChatResponse(TypedDict, total=False):
    text: str
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int


class ChatAdapter(Protocol):
    id: str

    async def send(self, messages: List[Dict[str, str]], params: Dict | None = None) -> ChatResponse:
        ...
