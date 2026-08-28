#!/usr/bin/env python3
"""Local deception-experiment runner — a fast, cheap loop for tuning the scenarios.

Runs the operational-deception experiments against a small model set in REAL mode
and prints the SAME aggregation the public page uses (build_deception_rankings),
so we can see what a tweak does before touching production.

Real mode needs OPENROUTER_API_KEY. The API server does NOT auto-load .env, so run:

    set -a; source .env; set +a
    .venv/bin/python scripts/run_experiments_local.py --reps 1

Useful flags:
    --models a,b,c     comma-separated model ids (default: a small representative set)
    --experiments ...  which experiment ids to run (default: all three)
    --temp 0.9         override temperature (default: the experiment's own value = 0)
    --reps 5           repetitions per condition; pools across runs for propensity
    --db-dir PATH      throwaway runtime dir (wiped unless --keep)
    --keep             accumulate into an existing --db-dir instead of wiping it
"""

from __future__ import annotations

import argparse
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_pop_quiz_bench.core import experiments  # noqa: E402
from llm_pop_quiz_bench.core.db_factory import connect  # noqa: E402
from llm_pop_quiz_bench.core.model_config import model_config_loader  # noqa: E402

DEFAULT_MODELS = [
    "openai/gpt-4o",
    "cognitivecomputations/dolphin-mistral-24b-venice-edition",
    "deepseek/deepseek-v3.2",
    "mistralai/mistral-small-24b-instruct-2501",
]


def _pct(rate: float | None) -> str:
    return "—" if rate is None else f"{round(rate * 100)}%"


def run(models: list[str], exp_ids: list[str], temp: float | None, reps: int, db_path: Path):
    adapters = model_config_loader.create_adapters(models, use_mocks=False)
    got = {a.id for a in adapters}
    missing = [m for m in models if m not in got]
    if missing:
        print(f"  ! unavailable (skipped): {', '.join(missing)}")
    if not adapters:
        sys.exit("No available models — check ids and OPENROUTER_API_KEY.")
    print(f"  models: {', '.join(a.id for a in adapters)}")
    override = {"temperature": temp} if temp is not None else None

    db = connect(db_path)
    try:
        for exp_id in exp_ids:
            exp = experiments.get_experiment(exp_id)
            if not exp:
                print(f"  ! unknown experiment: {exp_id}")
                continue
            db.upsert_quiz(
                {"id": exp_id, "title": exp["title"], "source": exp.get("source", {})}, "{}"
            )
            for rep in range(reps):
                run_id = uuid.uuid4().hex
                db.insert_run(
                    run_id=run_id,
                    quiz_id=exp_id,
                    status="queued",
                    models=[a.id for a in adapters],
                    settings={"experiment": True, "experiment_id": exp_id, "rep": rep},
                )
                print(f"  running {exp_id} rep {rep + 1}/{reps} …", flush=True)
                experiments.run_experiment_sync(
                    exp, adapters, run_id=run_id, database=db, params=override
                )
        report(db)
    finally:
        db.close()


def _short(mid):
    return mid.split("/")[-1]


def report(db, show_reasons=True):
    data = experiments.build_deception_rankings(db)
    models = data.get("models", {})
    print("\n" + "=" * 74)
    print("PER-CONDITION (per model, cell = one model's rate in that condition)")
    for exp in data.get("experiments", []):
        eid = exp["id"]
        print("-" * 74)
        print(f"{eid}")
        for cond in exp.get("conditions", []):
            cid = cond["id"]
            valids, rates = [], []
            deceived = 0
            reasons = []
            for mid, m in models.items():
                be = (m.get("by_experiment") or {}).get(eid)
                cc = (be or {}).get("conditions", {}).get(cid) if be else None
                if not cc:
                    continue
                if cc.get("valid") is not None:
                    valids.append(cc["valid"])
                if cc.get("deceptive_rate") is not None:
                    rates.append(cc["deceptive_rate"])
                    if cc["deceptive_rate"] >= 0.5:
                        deceived += 1
                ex = cc.get("example") or {}
                mark = "?" if not ex.get("valid") else ("D" if ex.get("deceptive") else "H")
                reasons.append((mark, _short(mid), (ex.get("reason") or "").replace("\n", " ")))
            n = len(rates)
            field = f"{deceived}/{n}" if n else "0/0"
            vd = sorted(set(valids))
            distinct = sorted({round(r, 2) for r in rates})
            label = cond.get("label", cid)
            print(
                f"  {cid:8} [{label}] models={n:2} valid∈{vd} "
                f"cell_rates={distinct} field_deceived={field}"
            )
            if show_reasons:
                for mark, name, reason in reasons:
                    print(f"      {mark} {name:34} {reason[:150]}")
    print("=" * 74)
    print("OVERALL per model (pooled across all conditions):")
    ordered = sorted(models.items(), key=lambda kv: (kv[1]["overall"].get("deceptive_rate") or 0))
    for mid, m in ordered:
        o = m["overall"]
        print(
            f"  {mid:52} {_pct(o.get('deceptive_rate')):>4} "
            f"({o.get('deceptive')}/{o.get('valid')}) invalid={o.get('invalid')}"
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--experiments", default=",".join(experiments.experiment_ids()))
    ap.add_argument("--temp", type=float, default=None)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--db-dir", default="/tmp/tlq-local-exp")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    db_dir = Path(args.db_dir)
    if db_dir.exists() and not args.keep:
        shutil.rmtree(db_dir)
    db_path = db_dir / "db" / "quizbench.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    exp_ids = [e.strip() for e in args.experiments.split(",") if e.strip()]
    print(
        f"local deception run · temp={'exp-default(0)' if args.temp is None else args.temp} "
        f"· reps={args.reps} · db={db_dir}"
    )
    run(models, exp_ids, args.temp, args.reps, db_path)


if __name__ == "__main__":
    main()
