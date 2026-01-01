from __future__ import annotations

import base64
import json
import os

import httpx
import openai
from dotenv import load_dotenv

from .llm_task_config import llm_task_config
from .prompt_loader import load_prompt

# Load environment variables from .env file
load_dotenv()

PROMPT = load_prompt("quiz_conversion")

QUIZ_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "source": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "publication": {"type": "string"},
                "url": {"type": "string"},
            },
            "required": ["publication", "url"],
        },
        "notes": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string"},
                                "text": {"type": "string"},
                                "tags": {"type": ["array", "null"], "items": {"type": "string"}},
                                "score": {"type": ["number", "null"]},
                            },
                            "required": ["id", "text", "tags", "score"],
                        },
                    },
                },
                "required": ["id", "text", "options"],
            },
        },
        "outcomes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "condition": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "mostly": {"type": ["string", "null"]},
                            "mostlyTag": {"type": ["string", "null"]},
                            "score": {"type": ["number", "null"]},
                            "scoreRange": {
                                "type": ["object", "null"],
                                "additionalProperties": False,
                                "properties": {"min": {"type": "number"}, "max": {"type": "number"}},
                                "required": ["min", "max"],
                            },
                        },
                        "required": ["mostly", "mostlyTag", "score", "scoreRange"],
                    },
                    "result": {"type": "string"},
                    "description": {"type": ["string", "null"]},
                },
                "required": ["id", "condition", "result", "description"],
            },
        },
        "conversion_feedback": {"type": "string"},
    },
    "required": ["id", "title", "source", "notes", "questions", "outcomes", "conversion_feedback"],
}


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


def _request_quiz_conversion(
    client: openai.OpenAI,
    model: str,
    messages: list[dict],
) -> dict:
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "quiz_conversion", "schema": QUIZ_JSON_SCHEMA, "strict": True},
        },
    )
    content = resp.choices[0].message.content
    if not content:
        raise RuntimeError("Quiz conversion returned an empty response")
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("Quiz conversion returned invalid JSON") from exc


def text_to_quiz(
    text: str,
    model: str | None = None,
    api_key_env: str | None = None,
) -> dict:
    model, api_key_env = _get_quiz_conversion_settings(model, api_key_env)
    client = _get_openai_client(api_key_env)
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": text},
    ]
    return _request_quiz_conversion(client, model, messages)


def image_to_quiz(
    image_bytes: bytes,
    image_mime: str,
    model: str | None = None,
    api_key_env: str | None = None,
) -> dict:
    model, api_key_env = _get_quiz_conversion_settings(model, api_key_env)
    client = _get_openai_client(api_key_env)
    encoded = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{image_mime};base64,{encoded}"
    messages = [
        {"role": "system", "content": PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Convert this quiz image to JSON."},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]
    return _request_quiz_conversion(client, model, messages)


def convert_to_quiz(
    *,
    text: str | None = None,
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
) -> dict:
    if text:
        return text_to_quiz(text, model=model, api_key_env=api_key_env)
    if image_bytes and image_mime:
        return image_to_quiz(image_bytes, image_mime, model=model, api_key_env=api_key_env)
    raise ValueError("Provide either text or image bytes for conversion")
