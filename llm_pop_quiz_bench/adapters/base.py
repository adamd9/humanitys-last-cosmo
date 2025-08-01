from __future__ import annotations

from typing import Protocol, Union, TypedDict


class ChatResponse(TypedDict, total=False):
    text: str
    tokens_in: Union[int, None]
    tokens_out: Union[int, None]
    latency_ms: int


class ChatAdapter(Protocol):
    id: str

    async def send(
        self, messages: list[dict[str, str]], params: Union[dict, None] = None
    ) -> ChatResponse: ...
