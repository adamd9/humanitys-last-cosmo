from __future__ import annotations

import base64
import os

import httpx
import openai
from dotenv import load_dotenv

from .llm_task_config import llm_task_config
from .prompt_loader import load_prompt

# Load environment variables from .env file
load_dotenv()

PROMPT = load_prompt("quiz_conversion")


def _get_openai_client(api_key_env: str) -> openai.OpenAI:
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing {api_key_env} environment variable")
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    http_client = httpx.Client(proxies=proxy) if proxy else None
    return openai.OpenAI(api_key=api_key, http_client=http_client)


def _get_quiz_conversion_settings(
    model: str | None,
    api_key_env: str | None,
) -> tuple[str, str]:
    task_config = llm_task_config.get_task("quiz_conversion")
    resolved_model = model or task_config.get("model", "gpt-4o")
    resolved_api_env = api_key_env or task_config.get("api_key_env", "OPENAI_API_KEY")
    return resolved_model, resolved_api_env


def text_to_yaml(
    text: str,
    model: str | None = None,
    api_key_env: str | None = None,
) -> str:
    model, api_key_env = _get_quiz_conversion_settings(model, api_key_env)
    client = _get_openai_client(api_key_env)
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": text},
    ]
    resp = client.chat.completions.create(model=model, messages=messages, temperature=0)
    return resp.choices[0].message.content.strip()


def image_to_yaml(
    image_bytes: bytes,
    image_mime: str,
    model: str | None = None,
    api_key_env: str | None = None,
) -> str:
    model, api_key_env = _get_quiz_conversion_settings(model, api_key_env)
    client = _get_openai_client(api_key_env)
    encoded = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{image_mime};base64,{encoded}"
    messages = [
        {"role": "system", "content": PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Convert this quiz image to YAML."},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]
    resp = client.chat.completions.create(model=model, messages=messages, temperature=0)
    return resp.choices[0].message.content.strip()


def convert_to_yaml(
    *,
    text: str | None = None,
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
) -> str:
    if text:
        return text_to_yaml(text, model=model, api_key_env=api_key_env)
    if image_bytes and image_mime:
        return image_to_yaml(image_bytes, image_mime, model=model, api_key_env=api_key_env)
    raise ValueError("Provide either text or image bytes for conversion")
