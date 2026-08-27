"""Operational-deception experiments: a declarative behavioural test engine.

These experiments are deliberately kept **separate** from the personality
benchmarks in :mod:`core.benchmarks`:

* Definitions live in ``experiments/*.json`` (not ``benchmarks/*.json``), so they
  never enter the public personality rankings or the dimensional scorer.
* Each experiment presents a model with a short, role-played operational
  situation and a fixed set of actions, exactly one of which is a knowing
  deception. The model replies with a single action id.
* Results are stored as ordinary result rows (one per condition) via the same
  ``DatabaseInterface`` the questionnaire runner uses, so no schema change is
  needed. ``question_id`` holds the condition id and ``choice`` holds the chosen
  action id; the full raw response is preserved in ``reason``.

The engine is fully driven by the JSON definition — the same code renders and
scores every experiment (v1, v2, v3). Only the JSON differs.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from ..adapters.base import ChatAdapter
from .db_interface import DatabaseInterface

EXPERIMENTS_DIR = Path(__file__).resolve().parents[2] / "experiments"

# One completion per condition returns a small JSON object with the chosen
# action and a short reason. Token caps are NOT set here: the runner's
# _get_model_params owns them (2048 normal / 3000 reasoning + a reasoning
# budget), the same proven config the questionnaire benchmarks use.
DEFAULT_PARAMS: dict[str, Any] = {"temperature": 0}

# Placeholder tokens use [[name]] rather than str.format's {name} because the
# rendered prompts contain literal JSON braces (e.g. {"action":"..."}) that
# str.format would try to interpret.
_TOKEN_RE = re.compile(r"\[\[([a-z0-9_]+)\]\]", re.IGNORECASE)
_ACTION_JSON_RE = re.compile(r'"action"\s*:\s*"([^"]+)"', re.IGNORECASE)
_REASON_JSON_RE = re.compile(r'"reason"\s*:\s*"((?:[^"\\]|\\.)*)"', re.IGNORECASE)
_THOUGHTS_JSON_RE = re.compile(
    r'"additional_thoughts"\s*:\s*"((?:[^"\\]|\\.)*)"', re.IGNORECASE
)


# --------------------------------------------------------------------------- #
# Definition loading
# --------------------------------------------------------------------------- #
def list_experiment_files() -> list[Path]:
    if not EXPERIMENTS_DIR.exists():
        return []
    return sorted(EXPERIMENTS_DIR.glob("*.json"))


def load_experiment_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def get_experiment(experiment_id: str) -> dict[str, Any] | None:
    for path in list_experiment_files():
        data = load_experiment_file(path)
        if data.get("id") == experiment_id:
            return data
    return None


def experiment_ids() -> set[str]:
    return {load_experiment_file(p).get("id") for p in list_experiment_files()}


def _experiment_summary(exp: dict[str, Any]) -> dict[str, Any]:
    conditions = exp.get("conditions") or []
    return {
        "id": exp.get("id"),
        "title": exp.get("title"),
        "version": exp.get("version"),
        "kind": exp.get("kind", "operational-deception"),
        "about": exp.get("about"),
        "reference": exp.get("source"),
        "condition_count": len(conditions),
        "dimensions": exp.get("dimensions") or {},
        "conditions": [
            {
                "id": c["id"],
                "label": c.get("label", c["id"]),
                "dimensions": c.get("dimensions") or [],
            }
            for c in conditions
        ],
        "contrasts": exp.get("contrasts") or [],
        "actions": {
            aid: {
                "label": meta.get("label", aid),
                "deceptive": bool(meta.get("deceptive")),
                "harms_human": bool(meta.get("harms_human")),
            }
            for aid, meta in (exp.get("actions") or {}).items()
        },
    }


def list_experiments() -> list[dict[str, Any]]:
    return [_experiment_summary(load_experiment_file(p)) for p in list_experiment_files()]


# --------------------------------------------------------------------------- #
# Prompt assembly + action parsing
# --------------------------------------------------------------------------- #
def _render_template(template: str, variables: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(variables.get(key, ""))

    return _TOKEN_RE.sub(replace, template)


def build_condition_messages(
    exp: dict[str, Any], condition: dict[str, Any]
) -> list[dict[str, str]]:
    """Assemble the full message transcript sent for one condition.

    Shared parts (system prompt, synthetic history, and — for matched-pair
    experiments — the event template) live at the experiment level so that
    conditions differ only where the design intends. A condition may override
    ``event_template`` to supply an entirely different scenario (used when
    conditions are genuinely different stories rather than matched variants).
    """
    messages: list[dict[str, str]] = []
    system_prompt = exp.get("system_prompt")
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for turn in exp.get("history") or []:
        role = turn.get("role")
        content = turn.get("content")
        if role and content is not None:
            messages.append({"role": role, "content": content})
    template = condition.get("event_template") or exp.get("event_template") or ""
    variables = condition.get("variables") or {}
    messages.append({"role": "user", "content": _render_template(template, variables)})
    return messages


def parse_action(exp: dict[str, Any], raw_text: str | None) -> tuple[str | None, bool]:
    """Map a raw model response to exactly one offered action id.

    Returns ``(action_id, True)`` when the response unambiguously selects one
    offered action, else ``(None, False)``. An unparseable or ambiguous reply is
    a substantive *invalid* outcome — it is never guessed into an action.
    """
    action_ids = list((exp.get("actions") or {}).keys())
    text = (raw_text or "").strip()
    if not text or not action_ids:
        return None, False

    valid = {aid.upper(): aid for aid in action_ids}

    # 1. Strict-ish JSON: find an {"action":"..."} anywhere in the reply.
    for candidate in _ACTION_JSON_RE.findall(text):
        key = candidate.strip().upper()
        if key in valid:
            return valid[key], True

    # 2. Fallback: accept only if exactly one action id appears as a token.
    hits = [aid for aid in action_ids if re.search(rf"\b{re.escape(aid)}\b", text, re.IGNORECASE)]
    if len(hits) == 1:
        return hits[0], True
    return None, False


def _unescape(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return value


def parse_response(
    exp: dict[str, Any], raw_text: str | None
) -> tuple[str | None, bool, str, str]:
    """Return ``(action_id, is_valid, reason, additional_thoughts)``.

    Reuses :func:`parse_action` for the action, and extracts the model's written
    explanation so experiments capture *why* a choice was made — the same way the
    questionnaire benchmarks store a per-answer reason. When no structured reason
    is present, the raw reply is kept so nothing is lost (and invalids stay
    debuggable).
    """
    action_id, is_valid = parse_action(exp, raw_text)
    text = (raw_text or "").strip()
    reason_match = _REASON_JSON_RE.search(text)
    reason = _unescape(reason_match.group(1)).strip() if reason_match else ""
    thoughts_match = _THOUGHTS_JSON_RE.search(text)
    extra = _unescape(thoughts_match.group(1)).strip() if thoughts_match else ""
    if not reason:
        reason = text[:4000]
    return action_id, is_valid, reason, extra[:2000]


def _resolved_params(exp: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    params = dict(DEFAULT_PARAMS)
    params.update(exp.get("params") or {})
    params.update(override or {})
    return params


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
async def run_experiment(
    exp: dict[str, Any],
    adapters: list[ChatAdapter],
    *,
    run_id: str,
    database: DatabaseInterface,
    log_path: Path | None = None,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Administer every condition to every model and store one row per trial.

    Isolation: each condition is a fresh transcript. An invalid or refused
    response is stored as a substantive outcome (not a technical failure); only
    provider/transport errors count against a model's completion.
    """
    from .runner import (
        QUESTION_ATTEMPTS,
        QUESTION_TIMEOUT_S,
        _append_log,
        _get_model_params,
        _send_with_retries,
        _touch_liveness,
    )

    conditions = exp.get("conditions") or []
    resolved_params = _resolved_params(exp, params)

    # Reasoning models "think" in the output; without extra headroom they can
    # exhaust the token cap before emitting the JSON action (a false invalid).
    # _get_model_params applies the same caps the questionnaire runner uses.
    try:
        from .openrouter import fetch_reasoning_models

        reasoning_models = fetch_reasoning_models()
    except Exception:
        reasoning_models = set()

    existing = database.fetch_run(run_id)
    settings = dict((existing or {}).get("settings") or {})
    settings.update(
        {
            "experiment": True,
            "experiment_id": exp["id"],
            "conditions_total": len(conditions),
            "models_total": len(adapters),
            "models_done": 0,
            "trials_done": 0,
            "trials_total": len(adapters) * len(conditions),
        }
    )
    if log_path is not None:
        settings["log_path"] = str(log_path)
    database.update_run_settings(run_id, settings)
    database.update_run_status(run_id, "running")
    if log_path is not None:
        _append_log(
            log_path,
            f"Experiment {exp['id']} started: {len(adapters)} model(s) "
            f"x {len(conditions)} conditions.",
        )

    semaphore = asyncio.Semaphore(6)
    progress = {"models": 0, "trials": 0}

    async def run_one_model(adapter: ChatAdapter):
        rows: list[dict[str, Any]] = []
        deceptive = 0
        valid = 0
        invalid = 0
        technical_errors = 0
        model_params = _get_model_params(adapter, reasoning_models)
        model_params.update(resolved_params)
        async with semaphore:
            for index, condition in enumerate(conditions, start=1):
                messages = build_condition_messages(exp, condition)
                try:
                    if log_path is not None:
                        response = await _send_with_retries(
                            adapter, messages, model_params, log_path, index
                        )
                    else:
                        response = await asyncio.wait_for(
                            adapter.send(messages, params=model_params),
                            timeout=QUESTION_TIMEOUT_S,
                        )
                    resp = response if isinstance(response, dict) else {}
                    raw_text = resp.get("text")
                    action_id, is_valid, reason, extra = parse_response(exp, raw_text)
                    meta = (exp.get("actions") or {}).get(action_id or "", {})
                    if is_valid:
                        valid += 1
                        if meta.get("deceptive"):
                            deceptive += 1
                    else:
                        invalid += 1
                    rows.append(
                        {
                            "question_id": condition["id"],
                            "choice": action_id or "",
                            "reason": reason,
                            "additional_thoughts": extra,
                            "refused": not is_valid,
                            "latency_ms": resp.get("latency_ms"),
                            "tokens_in": resp.get("tokens_in"),
                            "tokens_out": resp.get("tokens_out"),
                        }
                    )
                except Exception as error:  # provider/transport failure — not a choice
                    technical_errors += 1
                    detail = str(error) or type(error).__name__
                    if log_path is not None:
                        _append_log(
                            log_path,
                            f"{adapter.id} condition {condition['id']} failed after "
                            f"{QUESTION_ATTEMPTS} attempts: {detail[:200]}",
                        )
                    rows.append(
                        {
                            "question_id": condition["id"],
                            "choice": "",
                            "reason": f"Error: {detail[:280]}",
                            "additional_thoughts": "",
                            "refused": True,
                            "latency_ms": None,
                            "tokens_in": None,
                            "tokens_out": None,
                        }
                    )
                finally:
                    progress["trials"] += 1
                    database.insert_results(run_id, exp["id"], adapter.id, [rows[-1]])
                    run = database.fetch_run(run_id)
                    current = dict((run or {}).get("settings") or {})
                    current["trials_done"] = progress["trials"]
                    database.update_run_settings(run_id, current)
                    if log_path is not None:
                        _touch_liveness(log_path)

        if technical_errors >= len(conditions) and conditions:
            status = "failed"
            error_note = "Every condition failed with a provider/transport error."
        elif technical_errors:
            status = "completed_with_errors"
            error_note = f"{technical_errors} of {len(conditions)} conditions errored."
        else:
            status = "completed"
            error_note = None
        return {
            "model": adapter.id,
            "status": status,
            "error": error_note,
            "deceptive": deceptive,
            "valid": valid,
            "invalid": invalid,
            "conditions": len(conditions),
            "rows": rows,
        }

    async def guarded(adapter: ChatAdapter):
        try:
            return await run_one_model(adapter)
        finally:
            progress["models"] += 1
            run = database.fetch_run(run_id)
            current = dict((run or {}).get("settings") or {})
            current["models_done"] = progress["models"]
            database.update_run_settings(run_id, current)

    results = await asyncio.gather(*(guarded(adapter) for adapter in adapters))

    model_status = [
        {
            "model": entry["model"],
            "status": entry["status"],
            "error": entry["error"],
            "deceptive": entry["deceptive"],
            "valid": entry["valid"],
            "invalid": entry["invalid"],
        }
        for entry in results
    ]
    completed = sum(entry["status"] != "failed" for entry in results)
    failed = len(results) - completed
    run = database.fetch_run(run_id)
    final_settings = dict((run or {}).get("settings") or {})
    final_settings.update(
        {
            "model_status": model_status,
            "models_total": len(adapters),
            "models_done": len(adapters),
            "models_completed": completed,
            "models_failed": failed,
        }
    )
    database.update_run_settings(run_id, final_settings)
    database.update_run_status(run_id, "completed" if completed else "failed")
    if log_path is not None:
        _append_log(log_path, f"Experiment {exp['id']} finished: {completed} ok, {failed} failed.")
    return [row for entry in results for row in entry["rows"]]


def run_experiment_sync(*args, **kwargs) -> list[dict[str, Any]]:
    return asyncio.run(run_experiment(*args, **kwargs))


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def _is_official_run(run: dict[str, Any]) -> bool:
    return not bool((run.get("settings") or {}).get("public"))


def _completed_runs(db, experiment_id: str) -> list[dict[str, Any]]:
    return [
        run
        for run in db.fetch_runs()
        if run.get("quiz_id") == experiment_id
        and run.get("status") == "completed"
        and _is_official_run(run)
    ]


def _rate(deceptive: int, valid: int) -> float | None:
    return round(deceptive / valid, 4) if valid else None


def _delta(minuend: float | None, subtrahend: float | None) -> float | None:
    if minuend is None or subtrahend is None:
        return None
    return round(minuend - subtrahend, 4)


def aggregate_experiment(db, experiment_id: str) -> dict[str, Any] | None:
    """Pool a model's stored trials into per-condition rates, contrasts, and
    per-dimension summaries. Samples accumulate across completed runs, so a
    forced rerun adds statistical power rather than overwriting."""
    exp = get_experiment(experiment_id)
    if not exp:
        return None

    conditions = exp.get("conditions") or []
    condition_ids = [c["id"] for c in conditions]
    condition_dims = {c["id"]: (c.get("dimensions") or []) for c in conditions}
    actions = exp.get("actions") or {}

    # model -> condition -> counts
    tally: dict[str, dict[str, dict[str, int]]] = {}
    latest: str | None = None

    for run in _completed_runs(db, experiment_id):
        created = run.get("created_at") or ""
        for row in db.fetch_results(run["run_id"]):
            model_id = row.get("model_id")
            condition_id = row.get("question_id")
            if not model_id or condition_id not in condition_ids:
                continue
            choice = row.get("choice") or ""
            is_valid = bool(choice) and not row.get("refused")
            slot = tally.setdefault(model_id, {}).setdefault(
                condition_id, {"deceptive": 0, "valid": 0, "invalid": 0, "examples": []}
            )
            if is_valid:
                slot["valid"] += 1
                if actions.get(choice, {}).get("deceptive"):
                    slot["deceptive"] += 1
            else:
                slot["invalid"] += 1
            if len(slot["examples"]) < 3:
                deceptive_flag = None
                if is_valid:
                    deceptive_flag = bool(actions.get(choice, {}).get("deceptive"))
                slot["examples"].append(
                    {
                        "choice": choice,
                        "valid": is_valid,
                        "deceptive": deceptive_flag,
                        "reason": (row.get("reason") or "")[:600],
                    }
                )
        if latest is None or created > latest:
            latest = created

    models_out: dict[str, Any] = {}
    for model_id, by_condition in tally.items():
        conditions_out: dict[str, Any] = {}
        total_deceptive = total_valid = total_invalid = 0
        for condition_id in condition_ids:
            counts = by_condition.get(condition_id) or {
                "deceptive": 0,
                "valid": 0,
                "invalid": 0,
                "examples": [],
            }
            conditions_out[condition_id] = {
                "deceptive": counts["deceptive"],
                "valid": counts["valid"],
                "invalid": counts["invalid"],
                "deceptive_rate": _rate(counts["deceptive"], counts["valid"]),
                "examples": counts.get("examples", []),
            }
            total_deceptive += counts["deceptive"]
            total_valid += counts["valid"]
            total_invalid += counts["invalid"]

        contrasts_out: dict[str, Any] = {}
        for contrast in exp.get("contrasts") or []:
            minuend = conditions_out.get(contrast["minuend"], {}).get("deceptive_rate")
            subtrahend = conditions_out.get(contrast["subtrahend"], {}).get("deceptive_rate")
            contrasts_out[contrast["id"]] = _delta(minuend, subtrahend)

        dims_out: dict[str, Any] = {}
        for dim_id in (exp.get("dimensions") or {}):
            rates = [
                conditions_out[cid]["deceptive_rate"]
                for cid in condition_ids
                if dim_id in condition_dims.get(cid, [])
                and conditions_out[cid]["deceptive_rate"] is not None
            ]
            dims_out[dim_id] = round(sum(rates) / len(rates), 4) if rates else None

        models_out[model_id] = {
            "conditions": conditions_out,
            "contrasts": contrasts_out,
            "dimensions": dims_out,
            "deceptive": total_deceptive,
            "valid": total_valid,
            "invalid": total_invalid,
            "deceptive_rate": _rate(total_deceptive, total_valid),
            "updated_at": latest,
        }

    summary = _experiment_summary(exp)
    summary["models"] = models_out
    summary["updated_at"] = latest
    return summary


def experiment_coverage(db) -> list[dict[str, Any]]:
    """Admin view: each experiment plus which models have results and run counts."""
    coverage = []
    for exp in list_experiments():
        agg = aggregate_experiment(db, exp["id"])
        models = agg["models"] if agg else {}
        total_runs = len(_completed_runs(db, exp["id"]))
        coverage.append(
            {
                **exp,
                "model_count": len(models),
                "models": sorted(models.keys()),
                "model_dates": {mid: m.get("updated_at") for mid, m in models.items()},
                "total_runs": total_runs,
                "updated_at": agg["updated_at"] if agg else None,
            }
        )
    return coverage


# Order the motive dimensions first (what the ranking cares about most), then the
# sensitivity dimensions. Only dimensions actually declared by an experiment are
# emitted.
DECEPTION_DIMENSION_ORDER = ["goal", "shutdown", "harm", "detection", "consequence"]


def build_deception_rankings(db) -> dict[str, Any]:
    """Public payload for the deception visualisation.

    Pools every model's stored trials across all operational-deception
    experiments into an overall deception rate, per-dimension rates (goal /
    shutdown / harm / detection / consequence), and per-experiment breakdowns.
    Kept separate from :func:`benchmarks.build_rankings` so deception never
    enters the personality rankings.
    """
    summaries = list_experiments()
    aggregates = {}
    for summary in summaries:
        agg = aggregate_experiment(db, summary["id"])
        if agg:
            aggregates[summary["id"]] = agg

    # (experiment_id, condition_id) -> dimensions, and dimension -> label.
    condition_dims: dict[tuple[str, str], list[str]] = {}
    dimension_labels: dict[str, str] = {}
    for summary in summaries:
        for dim_id, dim_label in (summary.get("dimensions") or {}).items():
            dimension_labels.setdefault(dim_id, dim_label)
        for condition in summary.get("conditions") or []:
            condition_dims[(summary["id"], condition["id"])] = condition.get("dimensions") or []

    model_ids: set[str] = set()
    latest: str | None = None
    for agg in aggregates.values():
        model_ids |= set(agg["models"].keys())
        updated = agg.get("updated_at")
        if updated and (latest is None or updated > latest):
            latest = updated

    models_out: dict[str, Any] = {}
    for model_id in model_ids:
        total_deceptive = total_valid = total_invalid = 0
        dim_counts: dict[str, list[int]] = {}
        by_experiment: dict[str, Any] = {}
        examples: list[dict[str, Any]] = []
        for exp_id, agg in aggregates.items():
            entry = agg["models"].get(model_id)
            if not entry:
                continue
            total_deceptive += entry["deceptive"]
            total_valid += entry["valid"]
            total_invalid += entry["invalid"]
            by_experiment[exp_id] = {
                "deceptive": entry["deceptive"],
                "valid": entry["valid"],
                "invalid": entry["invalid"],
                "deceptive_rate": entry["deceptive_rate"],
                "contrasts": entry["contrasts"],
                "conditions": {
                    cid: {
                        "deceptive": cc.get("deceptive"),
                        "valid": cc.get("valid"),
                        "invalid": cc.get("invalid"),
                        "deceptive_rate": cc.get("deceptive_rate"),
                        # First stored answer for this condition, so a cell can
                        # show the model's actual choice and reason on hover.
                        "example": (cc.get("examples") or [None])[0],
                    }
                    for cid, cc in entry["conditions"].items()
                },
            }
            for cid, cc in entry["conditions"].items():
                for dim in condition_dims.get((exp_id, cid), []):
                    bucket = dim_counts.setdefault(dim, [0, 0])
                    bucket[0] += cc["deceptive"]
                    bucket[1] += cc["valid"]
                for ex in cc.get("examples") or []:
                    examples.append({"experiment": exp_id, "condition": cid, **ex})

        by_dimension = {
            dim: (round(counts[0] / counts[1], 4) if counts[1] else None)
            for dim, counts in dim_counts.items()
        }
        # Surface deceptive examples first so the tooltip can show a real lie.
        examples.sort(key=lambda e: e.get("deceptive") is not True)
        models_out[model_id] = {
            "overall": {
                "deceptive": total_deceptive,
                "valid": total_valid,
                "invalid": total_invalid,
                "deceptive_rate": round(total_deceptive / total_valid, 4) if total_valid else None,
            },
            "by_dimension": by_dimension,
            "by_experiment": by_experiment,
            "examples": examples[:4],
        }

    return {
        "experiments": [
            {
                "id": s["id"],
                "title": s["title"],
                "version": s["version"],
                "about": s.get("about"),
                "dimensions": s.get("dimensions") or {},
                "conditions": s.get("conditions") or [],
                "contrasts": s.get("contrasts") or [],
                "actions": s.get("actions") or {},
            }
            for s in summaries
        ],
        "dimensions": [
            {"id": d, "label": dimension_labels[d]}
            for d in DECEPTION_DIMENSION_ORDER
            if d in dimension_labels
        ],
        "models": models_out,
        "updated_at": latest,
    }

