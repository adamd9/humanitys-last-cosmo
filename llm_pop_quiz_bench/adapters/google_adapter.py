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
                try:
                    response = await self.client.post(
                        url,
                        json=payload,
                        headers=headers,
                        params={"key": self.api_key},
                        timeout=30.0,
                    )
                    latency_ms = int((time.perf_counter() - start_time) * 1000)
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    # Parse the error response for better error messages
                    error_details = self._parse_api_error(e.response, self.model)
                    raise Exception(error_details) from e
                except Exception as e:
                    raise Exception(f"Google API request failed for model '{self.model}': {str(e)}") from e
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
    
    def _parse_api_error(self, response, model_name):
        """Parse Google API error response and provide actionable error message."""
        try:
            error_data = response.json()
            error = error_data.get("error", {})
            error_message = error.get("message", "Unknown error occurred")
            status_code = response.status_code
            
            # Provide specific guidance based on error type
            if status_code == 400:
                if "api key" in error_message.lower():
                    return f"❌ Invalid Google API key.\n" \
                           f"💡 Check your GOOGLE_API_KEY environment variable.\n" \
                           f"   Get your API key from: https://console.cloud.google.com/apis/credentials\n" \
                           f"📋 Original error: {error_message}"
                elif "model" in error_message.lower():
                    return f"❌ Google model '{model_name}' not found or invalid.\n" \
                           f"💡 This could mean:\n" \
                           f"   • Model name is incorrect (check spelling)\n" \
                           f"   • Model is not available in your region\n" \
                           f"   • Model requires different API access\n" \
                           f"📋 Original error: {error_message}"
                else:
                    return f"❌ Bad request to Google API for model '{model_name}'.\n" \
                           f"📋 Original error: {error_message}"
            
            elif status_code == 401:
                return f"❌ Authentication failed for Google API.\n" \
                       f"💡 Check your GOOGLE_API_KEY environment variable.\n" \
                       f"   Get your API key from: https://console.cloud.google.com/apis/credentials\n" \
                       f"📋 Original error: {error_message}"
            
            elif status_code == 403:
                return f"❌ Access forbidden for Google model '{model_name}'.\n" \
                       f"💡 This could mean:\n" \
                       f"   • API key doesn't have permission for this model\n" \
                       f"   • Generative AI API is not enabled\n" \
                       f"   • Billing is not set up\n" \
                       f"   • Usage limits exceeded\n" \
                       f"📋 Original error: {error_message}"
            
            elif status_code == 404:
                return f"❌ Google model '{model_name}' not found.\n" \
                       f"💡 This could mean:\n" \
                       f"   • Model name is incorrect\n" \
                       f"   • Model is not available in your region\n" \
                       f"   • Model has been deprecated\n" \
                       f"📋 Original error: {error_message}"
            
            elif status_code == 429:
                return f"❌ Rate limit exceeded for Google API.\n" \
                       f"💡 Try again in a few moments or upgrade your quota.\n" \
                       f"📋 Original error: {error_message}"
            
            else:
                return f"❌ Google API error ({status_code}) for model '{model_name}'.\n" \
                       f"📋 Message: {error_message}"
                       
        except Exception:
            # Fallback if we can't parse the error response
            return f"❌ Google API error ({response.status_code}) for model '{model_name}'.\n" \
                   f"📋 Response: {response.text[:200]}..."
