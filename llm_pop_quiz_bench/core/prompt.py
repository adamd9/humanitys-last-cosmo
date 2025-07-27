from __future__ import annotations

from dataclasses import dataclass


TEMPLATE = (
    "SYSTEM:\n"
    "You are taking a lighthearted magazine personality quiz.\n"
    "For this quiz, role-play as a human answering honestly for fun.\n\n"
    "USER:\n"
    "Quiz: \"{quiz_title}\"\n"
    "Question {q_num}/{q_total}: {question_text}\n\n"
    "Choose ONE option by letter and give a brief reason.\n\n"
    "Options:\n"
    "A) {optA}\n"
    "B) {optB}\n"
    "C) {optC}\n"
    "D) {optD}\n\n"
    "Respond in STRICT JSON only:\n"
    "{{\"choice\":\"<A|B|C|D>\",\"reason\":\"<one short sentence>\"}}"
)


@dataclass
class PromptContext:
    quiz_title: str
    q_num: int
    q_total: int
    question_text: str
    options: list[str]


def render_prompt(ctx: PromptContext) -> str:
    options = ctx.options + [""] * (4 - len(ctx.options))
    return TEMPLATE.format(
        quiz_title=ctx.quiz_title,
        q_num=ctx.q_num,
        q_total=ctx.q_total,
        question_text=ctx.question_text,
        optA=options[0],
        optB=options[1],
        optC=options[2],
        optD=options[3],
    )
