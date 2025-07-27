from __future__ import annotations

import os

import openai

PROMPT = (
    "You convert magazine-style quizzes to YAML. "
    "Use keys: id, title, source{publication,url}, notes, questions, outcomes. "
    "Each question has id, text and options with id, text, optional tags or score."
    "Outcome conditions may use mostly, mostlyTag or scoreRange. "
    "Return only valid YAML."
)


def text_to_yaml(text: str, model: str = "gpt-4o", api_key_env: str = "OPENAI_API_KEY") -> str:
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing {api_key_env} environment variable")
    client = openai.OpenAI(api_key=api_key)
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": text},
    ]
    resp = client.chat.completions.create(model=model, messages=messages, temperature=0)
    return resp.choices[0].message.content.strip()
