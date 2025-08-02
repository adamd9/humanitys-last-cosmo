from __future__ import annotations

from dataclasses import dataclass
from string import ascii_uppercase

TEMPLATE = (
    "SYSTEM:\n"
    "You are an AI language model, so you lack human experiences. That's OK.\n"
    "For each question I send, choose **exactly one** of the provided options that best matches the linguistic patterns you typically produce.\n"
    "USER:\n"
    "Question {q_num}/{q_total}: {question_text}\n\n"
    "Choose ONE option by letter and provide your reasoning.\n\n"
    "Options:\n"
    "{options_text}\n"
    "Respond in STRICT JSON format with your choice and detailed reasoning:\n"
    '{{"choice":"<{valid_choices}>","reason":"<explain your reasoning in 1-2 sentences>","additional_thoughts":"<any extra thoughts or personality insights (optional)>"}}'
)


@dataclass
class PromptContext:
    quiz_title: str
    q_num: int
    q_total: int
    question_text: str
    options: list[str]


def render_prompt(ctx: PromptContext) -> str:
    # Generate dynamic options text and valid choices
    options_lines = []
    valid_choices = []
    
    for i, option_text in enumerate(ctx.options):
        letter = ascii_uppercase[i]  # A, B, C, D, E, F, etc.
        options_lines.append(f"{letter}) {option_text}")
        valid_choices.append(letter)
    
    options_text = "\n".join(options_lines)
    valid_choices_str = "|".join(valid_choices)  # "A|B|C|D" or "A|B|C|D|E|F"
    
    return TEMPLATE.format(
        q_num=ctx.q_num,
        q_total=ctx.q_total,
        question_text=ctx.question_text,
        options_text=options_text,
        valid_choices=valid_choices_str,
    )
