"""MongoDB database implementation using the DatabaseInterface."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    from pymongo import MongoClient
    from pymongo.collection import Collection
    from pymongo.database import Database
    PYMONGO_AVAILABLE = True
except ImportError:
    PYMONGO_AVAILABLE = False
    MongoClient = None
    Collection = None
    Database = None

from .db_interface import DatabaseInterface


class MongoDatabase(DatabaseInterface):
    """MongoDB implementation of the database interface."""

    def __init__(self, client: "MongoClient", db_name: str = "quizbench"):
        if not PYMONGO_AVAILABLE:
            raise ImportError("pymongo is required for MongoDB support")
        self.client = client
        self.db: Database = client[db_name]
        self.quizzes: Collection = self.db["quizzes"]
        self.runs: Collection = self.db["runs"]
        self.results: Collection = self.db["results"]
        self.assets: Collection = self.db["assets"]
        self.audit: Collection = self.db["audit"]
        self.outcomes: Collection = self.db["outcomes"]
        
        # Create indexes for better performance
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Create required indexes that are not already present."""
        indexes = (
            (self.quizzes, "quiz_id_1", "quiz_id", {"unique": True}),
            (self.runs, "run_id_1", "run_id", {"unique": True}),
            (self.runs, "quiz_id_1", "quiz_id", {}),
            (self.runs, "created_at_1", "created_at", {}),
            (self.results, "run_id_1_model_id_1", [("run_id", 1), ("model_id", 1)], {}),
            (self.assets, "run_id_1", "run_id", {}),
            (self.audit, "ip_1", "ip", {}),
            (self.audit, "run_id_1", "run_id", {}),
            (self.outcomes, "run_id_1", "run_id", {}),
        )
        known_by_collection = {}
        for collection, name, keys, options in indexes:
            collection_id = id(collection)
            if collection_id not in known_by_collection:
                known_by_collection[collection_id] = set(collection.index_information())
            if name not in known_by_collection[collection_id]:
                collection.create_index(keys, name=name, **options)
                known_by_collection[collection_id].add(name)

    def close(self) -> None:
        """Close database connection."""
        if self.client:
            self.client.close()

    def upsert_quiz(
        self,
        quiz_def: dict,
        quiz_json: str,
        raw_payload: dict | None = None,
    ) -> None:
        """Insert or update a quiz."""
        quiz_id = quiz_def["id"]
        title = quiz_def.get("title", "")
        source = quiz_def.get("source", {})
        created_at = datetime.now(timezone.utc).isoformat()
        
        doc = {
            "quiz_id": quiz_id,
            "title": title,
            "source": source,
            "quiz_json": quiz_json,
            "raw_payload": raw_payload or {},
            "created_at": created_at,
        }
        
        self.quizzes.update_one(
            {"quiz_id": quiz_id},
            {"$set": doc},
            upsert=True,
        )

    def insert_run(
        self,
        run_id: str,
        quiz_id: str,
        status: str,
        models: list[str],
        settings: dict | None = None,
    ) -> None:
        """Insert a new run."""
        created_at = datetime.now(timezone.utc).isoformat()
        doc = {
            "run_id": run_id,
            "quiz_id": quiz_id,
            "created_at": created_at,
            "status": status,
            "models": models,
            "settings": settings or {},
        }
        self.runs.update_one(
            {"run_id": run_id},
            {"$set": doc},
            upsert=True,
        )

    def update_run_status(self, run_id: str, status: str) -> None:
        """Update the status of a run."""
        self.runs.update_one(
            {"run_id": run_id},
            {"$set": {"status": status}},
        )

    def update_run_settings(self, run_id: str, settings: dict) -> None:
        """Replace the settings blob of a run."""
        self.runs.update_one(
            {"run_id": run_id},
            {"$set": {"settings": settings or {}}},
        )

    def mark_stale_runs_failed(
        self,
        statuses: Iterable[str] = ("queued", "running", "reporting"),
        new_status: str = "failed",
    ) -> list[str]:
        """Mark stale runs as failed and return their IDs."""
        status_list = list(statuses)
        if not status_list:
            return []
        
        cursor = self.runs.find({"status": {"$in": status_list}}, {"run_id": 1})
        run_ids = [doc["run_id"] for doc in cursor]
        
        if run_ids:
            self.runs.update_many(
                {"status": {"$in": status_list}},
                {"$set": {"status": new_status}},
            )
        
        return run_ids

    def insert_results(
        self,
        run_id: str,
        quiz_id: str,
        model_id: str,
        rows: Iterable[dict],
    ) -> None:
        """Insert result rows for a run."""
        docs = []
        for row in rows:
            doc = {
                "run_id": run_id,
                "quiz_id": quiz_id,
                "model_id": model_id,
                "question_id": row.get("question_id", ""),
                "choice": row.get("choice", ""),
                "reason": row.get("reason", ""),
                "additional_thoughts": row.get("additional_thoughts", ""),
                "refused": bool(row.get("refused")),
                "latency_ms": row.get("latency_ms"),
                "tokens_in": row.get("tokens_in"),
                "tokens_out": row.get("tokens_out"),
            }
            docs.append(doc)
        
        if docs:
            self.results.insert_many(docs)

    def insert_asset(self, run_id: str, asset_type: str, path: Path) -> None:
        """Insert an asset record."""
        created_at = datetime.now(timezone.utc).isoformat()
        doc = {
            "run_id": run_id,
            "asset_type": asset_type,
            "path": str(path),
            "created_at": created_at,
        }
        self.assets.insert_one(doc)

    def fetch_results(self, run_id: str) -> list[dict]:
        """Fetch all results for a run."""
        cursor = self.results.find(
            {"run_id": run_id},
            {"_id": 0}  # Exclude MongoDB's internal _id field
        )
        return [
            {
                "run_id": doc["run_id"],
                "quiz_id": doc["quiz_id"],
                "model_id": doc["model_id"],
                "question_id": doc["question_id"],
                "choice": doc["choice"],
                "reason": doc["reason"],
                "additional_thoughts": doc["additional_thoughts"],
                "refused": 1 if doc.get("refused") else 0,
                "latency_ms": doc.get("latency_ms"),
                "tokens_in": doc.get("tokens_in"),
                "tokens_out": doc.get("tokens_out"),
            }
            for doc in cursor
        ]

    def _quiz_titles(self, quiz_ids: list[str]) -> dict[str, str | None]:
        """Map quiz_id -> human title in a single query (parity with the SQLite
        ``q.title AS quiz_title`` join, so runs show the quiz's name not its id)."""
        ids = [qid for qid in dict.fromkeys(quiz_ids) if qid]
        if not ids:
            return {}
        cursor = self.quizzes.find(
            {"quiz_id": {"$in": ids}}, {"quiz_id": 1, "title": 1, "_id": 0}
        )
        return {doc["quiz_id"]: doc.get("title") for doc in cursor if doc.get("quiz_id")}

    def fetch_runs(self) -> list[dict]:
        """Fetch all runs, each annotated with its quiz's human title."""
        runs = list(self.runs.find({}, {"_id": 0}).sort("created_at", -1))
        titles = self._quiz_titles([run.get("quiz_id") for run in runs])
        for run in runs:
            run["quiz_title"] = titles.get(run.get("quiz_id"))
        return runs

    def fetch_run(self, run_id: str) -> dict | None:
        """Fetch a specific run by ID, annotated with its quiz's human title."""
        doc = self.runs.find_one({"run_id": run_id}, {"_id": 0})
        if doc:
            titles = self._quiz_titles([doc.get("quiz_id")])
            doc["quiz_title"] = titles.get(doc.get("quiz_id"))
        return doc

    def fetch_assets(self, run_id: str) -> list[dict]:
        """Fetch all assets for a run."""
        cursor = self.assets.find(
            {"run_id": run_id},
            {"_id": 0}
        ).sort("created_at", -1)
        return list(cursor)

    def delete_assets_for_run(self, run_id: str) -> None:
        """Delete all assets for a run."""
        self.assets.delete_many({"run_id": run_id})

    def fetch_quiz_json(self, quiz_id: str) -> str | None:
        """Fetch quiz JSON by ID."""
        doc = self.quizzes.find_one({"quiz_id": quiz_id}, {"quiz_json": 1, "_id": 0})
        return doc.get("quiz_json") if doc else None

    def fetch_quizzes(self) -> list[dict]:
        """Fetch all quizzes."""
        cursor = self.quizzes.find(
            {},
            {
                "quiz_id": 1,
                "title": 1,
                "source": 1,
                "created_at": 1,
                "raw_payload": 1,
                "_id": 0,
            }
        ).sort("created_at", -1)
        
        items = []
        for doc in cursor:
            item = {
                "quiz_id": doc.get("quiz_id"),
                "title": doc.get("title"),
                "source": doc.get("source", {}),
                "created_at": doc.get("created_at"),
                "raw_available": bool(doc.get("raw_payload")),
            }
            items.append(item)
        return items

    def fetch_quiz_def(self, quiz_id: str) -> dict | None:
        """Fetch quiz definition by ID."""
        doc = self.quizzes.find_one({"quiz_id": quiz_id}, {"quiz_json": 1, "_id": 0})
        if not doc or not doc.get("quiz_json"):
            return None
        return json.loads(doc["quiz_json"])

    def fetch_quiz_record(self, quiz_id: str) -> dict | None:
        """Fetch full quiz record including raw payload."""
        doc = self.quizzes.find_one(
            {"quiz_id": quiz_id},
            {"quiz_json": 1, "raw_payload": 1, "_id": 0}
        )
        if not doc:
            return None
        
        quiz_json = doc.get("quiz_json", "")
        raw_payload = doc.get("raw_payload", {})
        
        return {
            "quiz": json.loads(quiz_json) if quiz_json else {},
            "quiz_json": quiz_json,
            "raw_payload": raw_payload,
        }

    def delete_quiz(self, quiz_id: str) -> list[str]:
        """Delete a quiz and return IDs of deleted runs."""
        # Find all runs for this quiz
        cursor = self.runs.find({"quiz_id": quiz_id}, {"run_id": 1, "_id": 0})
        run_ids = [doc["run_id"] for doc in cursor]
        
        # Delete related data
        if run_ids:
            self.results.delete_many({"run_id": {"$in": run_ids}})
            self.assets.delete_many({"run_id": {"$in": run_ids}})
            self.runs.delete_many({"run_id": {"$in": run_ids}})
        
        # Delete the quiz itself
        self.quizzes.delete_one({"quiz_id": quiz_id})
        
        return run_ids

    def insert_audit(
        self,
        *,
        event: str,
        ip: str | None = None,
        run_id: str | None = None,
        quiz_id: str | None = None,
        models: list[str] | None = None,
        cost_usd: float | None = None,
        detail: dict | None = None,
    ) -> None:
        """Append an audit-log entry."""
        doc = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ip": ip,
            "event": event,
            "run_id": run_id,
            "quiz_id": quiz_id,
            "models": models or [],
            "cost_usd": cost_usd,
            "detail": detail or {},
        }
        self.audit.insert_one(doc)

    def count_events_for_ip_since(self, ip: str, event: str, since_iso: str) -> int:
        """Count audit events for an IP since a timestamp."""
        return self.audit.count_documents({
            "ip": ip,
            "event": event,
            "created_at": {"$gte": since_iso},
        })

    def sum_cost_for_ip_since(self, ip: str, since_iso: str) -> float:
        """Sum recorded cost for an IP since a timestamp."""
        cursor = self.audit.aggregate([
            {"$match": {
                "ip": ip,
                "cost_usd": {"$ne": None},
                "created_at": {"$gte": since_iso},
            }},
            {"$group": {"_id": None, "total": {"$sum": "$cost_usd"}}},
        ])
        for doc in cursor:
            return float(doc.get("total") or 0.0)
        return 0.0

    def fetch_ip_for_run(self, run_id: str) -> str | None:
        """Return the earliest recorded IP associated with a run."""
        doc = self.audit.find_one(
            {"run_id": run_id, "ip": {"$ne": None}},
            {"ip": 1, "_id": 0},
            sort=[("created_at", 1)],
        )
        return doc.get("ip") if doc else None

    def fetch_audit(self, since_iso: str | None = None) -> list[dict]:
        """Fetch audit-log entries (optionally only those at/after since_iso)."""
        query = {"created_at": {"$gte": since_iso}} if since_iso else {}
        return list(self.audit.find(query, {"_id": 0}).sort("created_at", 1))

    def replace_run_outcomes(
        self,
        run_id: str,
        quiz_id: str,
        outcomes: Iterable[dict],
    ) -> None:
        """Replace stored per-model outcomes for a run."""
        self.outcomes.delete_many({"run_id": run_id})
        created_at = datetime.now(timezone.utc).isoformat()
        docs = []
        for outcome in outcomes:
            model_id = outcome.get("model_id")
            if not model_id:
                continue
            docs.append({
                "run_id": run_id,
                "quiz_id": quiz_id,
                "model_id": str(model_id),
                "outcome": str(outcome.get("outcome", "")),
                "created_at": created_at,
            })
        if docs:
            self.outcomes.insert_many(docs)

    def fetch_run_outcomes(self, run_id: str) -> list[dict]:
        """Fetch stored per-model outcomes for a run."""
        cursor = self.outcomes.find(
            {"run_id": run_id},
            {"model_id": 1, "outcome": 1, "_id": 0},
        ).sort("created_at", 1)
        return [{"model_id": d.get("model_id"), "outcome": d.get("outcome")} for d in cursor]
