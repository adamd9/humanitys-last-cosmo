from __future__ import annotations

from typing import Any


def _collect_outcome_rule_types(outcome: dict[str, Any]) -> set[str]:
    rule_types: set[str] = set()
    condition = outcome.get("condition") if isinstance(outcome.get("condition"), dict) else {}

    if "mostly" in outcome or "mostly" in condition:
        rule_types.add("mostly")
    if "mostlyTag" in outcome or "mostlyTag" in condition:
        rule_types.add("mostlyTag")
    if "scoreRange" in outcome or "scoreRange" in condition:
        rule_types.add("scoreRange")

    return rule_types


def _infer_quiz_type(outcomes: list[dict[str, Any]], has_tags: bool, has_scores: bool) -> str:
    for outcome in outcomes:
        condition = outcome.get("condition") if isinstance(outcome.get("condition"), dict) else {}
        if condition.get("mostlyTag") or outcome.get("mostlyTag"):
            return "Tag-based"
        if condition.get("scoreRange") or outcome.get("scoreRange"):
            return "Score-based"
        if condition.get("mostly") or outcome.get("mostly"):
            return "Mostly letter"

    if has_tags:
        return "Tag-based"
    if has_scores:
        return "Score-based"
    return "Mostly letter"


def build_quiz_meta(quiz_def: dict[str, Any]) -> dict[str, Any]:
    questions = quiz_def.get("questions") or []
    outcomes = quiz_def.get("outcomes") or []

    has_tags = False
    has_scores = False
    choice_ids: set[str] = set()
    anonymous_choices = 0

    for question in questions:
        options = question.get("options") or question.get("choices") or []
        for option in options:
            option_id = option.get("id")
            if option_id:
                choice_ids.add(str(option_id))
            else:
                anonymous_choices += 1
            tags = option.get("tags") or []
            if tags:
                has_tags = True
            if isinstance(option.get("score"), (int, float)):
                has_scores = True

    rule_types: set[str] = set()
    for outcome in outcomes:
        rule_types.update(_collect_outcome_rule_types(outcome))

    quiz_type = _infer_quiz_type(outcomes, has_tags, has_scores)
    choice_count = len(choice_ids) + anonymous_choices

    return {
        "quiz_type": quiz_type,
        "has_outcomes": bool(outcomes),
        "outcome_count": len(outcomes),
        "outcome_rule_types": sorted(rule_types),
        "choice_count": choice_count,
        "has_tags": has_tags,
        "has_scores": has_scores,
    }
