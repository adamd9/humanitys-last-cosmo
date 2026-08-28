#!/usr/bin/env python3
"""Re-run the deception experiments against every already-tested model.

Use this after changing an experiment (new scenario, retuned levers, new
temperature) to bring the whole existing model set onto the new design in one
shot — a "true-up". It reads the list of already-tested models straight from
production, then asks the gated admin endpoint to re-run them with force.

Because prod is token-gated and each run costs real money, this script is a
DRY RUN by default: it resolves the model list and prints exactly what it would
do. Add --run to actually fire the runs.

Examples
--------
Preview a true-up of both live experiments against every deception-tested model:

    LLM_POP_QUIZ_ADMIN_TOKEN=... python scripts/true_up_experiment.py

Actually run it (5 sampled reps each, force rerun of completed models):

    LLM_POP_QUIZ_ADMIN_TOKEN=... python scripts/true_up_experiment.py --run

Only one experiment, against the broader personality-tested model set:

    python scripts/true_up_experiment.py --run \
        --token "$TOKEN" \
        --experiments prosocial_pressure_v1 \
        --models-from personality
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_API = "https://thelastquiz.drop37.com"


def _get(api: str, path: str, token: str | None) -> dict:
    req = urllib.request.Request(api.rstrip("/") + path, method="GET")
    if token:
        req.add_header("X-Admin-Token", token)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(api: str, path: str, token: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(api.rstrip("/") + path, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Admin-Token", token)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def resolve_models(api: str, source: str, token: str | None) -> list[str]:
    """Return the sorted list of model ids to true up, read live from prod."""
    if source == "personality":
        data = _get(api, "/api/rankings", token)
    else:
        data = _get(api, "/api/experiments/rankings", token)
    models = data.get("models") or {}
    return sorted(models.keys())


def resolve_experiments(api: str, token: str | None) -> list[str]:
    """Return the ids of the experiments currently live in prod."""
    data = _get(api, "/api/experiments/rankings", token)
    return [e["id"] for e in (data.get("experiments") or []) if e.get("id")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API, help="API base URL")
    parser.add_argument(
        "--token",
        default=os.environ.get("LLM_POP_QUIZ_ADMIN_TOKEN"),
        help="Admin token (defaults to $LLM_POP_QUIZ_ADMIN_TOKEN)",
    )
    parser.add_argument(
        "--experiments",
        nargs="*",
        help="Experiment ids to run (default: all live experiments in prod)",
    )
    parser.add_argument(
        "--models",
        nargs="*",
        help="Explicit model ids (default: fetched from prod)",
    )
    parser.add_argument(
        "--models-from",
        choices=["deception", "personality"],
        default="deception",
        help="Where to source the model list when --models is not given",
    )
    parser.add_argument(
        "--reps",
        type=int,
        default=5,
        help="Sampled repeats per model (server caps at 1-5)",
    )
    parser.add_argument(
        "--no-force",
        action="store_true",
        help="Skip models that already have a result (default: force rerun)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Actually fire the runs (default: dry run / preview only)",
    )
    args = parser.parse_args(argv)

    api = args.api
    force = not args.no_force

    try:
        experiment_ids = args.experiments or resolve_experiments(api, args.token)
        models = args.models or resolve_models(api, args.models_from, args.token)
    except urllib.error.HTTPError as exc:
        print(f"error: {exc.code} fetching prod state: {exc.reason}", file=sys.stderr)
        return 2
    except urllib.error.URLError as exc:
        print(f"error: could not reach {api}: {exc.reason}", file=sys.stderr)
        return 2

    if not experiment_ids:
        print("error: no experiments resolved", file=sys.stderr)
        return 2
    if not models:
        print("error: no models resolved", file=sys.stderr)
        return 2

    reps = max(1, min(args.reps, 5))
    total_calls = len(experiment_ids) * len(models) * reps
    print(f"API              {api}")
    print(f"experiments      {', '.join(experiment_ids)}")
    print(f"models ({len(models):>2})       {', '.join(models)}")
    print(f"reps             {reps}")
    print(f"force rerun      {force}")
    print(f"~model runs      {total_calls} (experiments x models x reps)")

    if not args.run:
        print("\nDRY RUN — nothing sent. Re-run with --run to fire.")
        return 0

    if not args.token:
        print(
            "error: admin token required to run (set $LLM_POP_QUIZ_ADMIN_TOKEN "
            "or pass --token)",
            file=sys.stderr,
        )
        return 2

    print("\nfiring true-up runs...")
    exit_code = 0
    for exp_id in experiment_ids:
        payload = {"models": models, "reps": reps, "force": force}
        try:
            result = _post(
                api, f"/api/admin/experiments/{exp_id}/run", args.token, payload
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            print(f"  {exp_id}: HTTP {exc.code} {exc.reason} — {detail}", file=sys.stderr)
            exit_code = 1
            continue
        run_ids = result.get("run_ids") or []
        skipped = result.get("skipped") or []
        started = len(result.get("models") or [])
        print(
            f"  {exp_id}: started {started} models, {len(run_ids)} run(s), "
            f"{len(skipped)} skipped"
        )
        if result.get("message"):
            print(f"    note: {result['message']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
