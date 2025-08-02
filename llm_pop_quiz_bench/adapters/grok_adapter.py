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
                try:
                    resp = await self.client.post("/chat/completions", json=payload, headers=headers, timeout=30)
                    resp.raise_for_status()
                except httpx.HTTPStatusError as e:
                    # Parse the error response for better error messages
                    error_details = self._parse_api_error(e.response, self.model)
                    raise Exception(error_details) from e
                except Exception as e:
                    raise Exception(f"Grok API request failed for model '{self.model}': {str(e)}") from e
        
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
    
    def _parse_api_error(self, response, model_name):
        """Parse Grok API error response and provide actionable error message."""
        try:
            error_data = response.json()
            error = error_data.get("error", {})
            error_type = error.get("type", "unknown_error")
            error_message = error.get("message", "Unknown error occurred")
            status_code = response.status_code
            
            # Provide specific guidance based on error type
            if status_code == 404:
                if "model" in error_message.lower():
                    return f"❌ Grok model '{model_name}' not found or not accessible.\n" \
                           f"💡 This could mean:\n" \
                           f"   • Model name is incorrect (check spelling)\n" \
                           f"   • Model is not available yet or deprecated\n" \
                           f"   • Model requires different API access level\n" \
                           f"📋 Original error: {error_message}"
                else:
                    return f"❌ Grok API endpoint not found (404).\n" \
                           f"💡 Check if the xAI API endpoint URL is correct.\n" \
                           f"📋 Original error: {error_message}"
            
            elif status_code == 401:
                return f"❌ Authentication failed for Grok API.\n" \
                       f"💡 Check your XAI_API_KEY environment variable.\n" \
                       f"   Get your API key from: https://console.x.ai/team/default/api-keys\n" \
                       f"📋 Original error: {error_message}"
            
            elif status_code == 403:
                return f"❌ Access forbidden for Grok model '{model_name}'.\n" \
                       f"💡 This could mean:\n" \
                       f"   • Your API key doesn't have access to this model\n" \
                       f"   • Usage limits exceeded\n" \
                       f"   • Account verification required\n" \
                       f"📋 Original error: {error_message}"
            
            elif status_code == 429:
                return f"❌ Rate limit exceeded for Grok API.\n" \
                       f"💡 Try again in a few moments or check your usage limits.\n" \
                       f"📋 Original error: {error_message}"
            
            else:
                return f"❌ Grok API error ({status_code}) for model '{model_name}'.\n" \
                       f"📋 Error type: {error_type}\n" \
                       f"📋 Message: {error_message}"
                       
        except Exception:
            # Fallback if we can't parse the error response
            return f"❌ Grok API error ({response.status_code}) for model '{model_name}'.\n" \
                   f"📋 Response: {response.text[:200]}..."
