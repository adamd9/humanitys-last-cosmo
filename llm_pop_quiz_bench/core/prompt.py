from __future__ import annotations

from dataclasses import dataclass
from string import ascii_uppercase

from .prompt_loader import load_prompt

TEMPLATE = load_prompt("quiz_question")


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
