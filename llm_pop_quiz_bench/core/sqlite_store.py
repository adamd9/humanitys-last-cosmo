from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml

def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            quiz_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            models_json TEXT NOT NULL,
            settings_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS quizzes (
            quiz_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            source_json TEXT NOT NULL,
            quiz_yaml TEXT NOT NULL,
            raw_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            quiz_id TEXT NOT NULL,
            model_id TEXT NOT NULL,
            question_id TEXT NOT NULL,
            choice TEXT NOT NULL,
            reason TEXT NOT NULL,
            additional_thoughts TEXT NOT NULL,
            refused INTEGER NOT NULL,
            latency_ms INTEGER,
            tokens_in INTEGER,
            tokens_out INTEGER
        );

        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            path TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    _ensure_column(conn, "quizzes", "raw_json", "TEXT NOT NULL DEFAULT '{}'", "{}")
    timestamp = datetime.now(timezone.utc).isoformat()
    _ensure_column(
        conn,
        "quizzes",
        "created_at",
        f"TEXT NOT NULL DEFAULT '{timestamp}'",
        timestamp,
    )
    conn.commit()


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
    default_value: str | None = None,
) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column in columns:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    if default_value is not None:
        conn.execute(f"UPDATE {table} SET {column} = ? WHERE {column} IS NULL", (default_value,))
    conn.commit()


def upsert_quiz(
    conn: sqlite3.Connection,
    quiz_def: dict,
    quiz_yaml: str,
    raw_payload: dict | None = None,
) -> None:
    quiz_id = quiz_def["id"]
    title = quiz_def.get("title", "")
    source_json = json.dumps(quiz_def.get("source", {}), ensure_ascii=False)
    raw_json = json.dumps(raw_payload or {}, ensure_ascii=False)
    created_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO quizzes (quiz_id, title, source_json, quiz_yaml, raw_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(quiz_id) DO UPDATE SET
            title=excluded.title,
            source_json=excluded.source_json,
            quiz_yaml=excluded.quiz_yaml,
            raw_json=excluded.raw_json
        """,
        (quiz_id, title, source_json, quiz_yaml, raw_json, created_at),
    )
    conn.commit()


def insert_run(
    conn: sqlite3.Connection,
    run_id: str,
    quiz_id: str,
    status: str,
    models: list[str],
    settings: dict | None = None,
) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT OR REPLACE INTO runs
        (run_id, quiz_id, created_at, status, models_json, settings_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            quiz_id,
            created_at,
            status,
            json.dumps(models, ensure_ascii=False),
            json.dumps(settings or {}, ensure_ascii=False),
        ),
    )
    conn.commit()


def update_run_status(conn: sqlite3.Connection, run_id: str, status: str) -> None:
    conn.execute("UPDATE runs SET status=? WHERE run_id=?", (status, run_id))
    conn.commit()


def mark_stale_runs_failed(
    conn: sqlite3.Connection,
    statuses: Iterable[str] = ("queued", "running", "reporting"),
    new_status: str = "failed",
) -> list[str]:
    status_list = list(statuses)
    if not status_list:
        return []
    placeholders = ", ".join(["?"] * len(status_list))
    rows = conn.execute(
        f"SELECT run_id FROM runs WHERE status IN ({placeholders})",
        status_list,
    ).fetchall()
    run_ids = [row["run_id"] for row in rows]
    if run_ids:
        conn.execute(
            f"UPDATE runs SET status = ? WHERE status IN ({placeholders})",
            (new_status, *status_list),
        )
        conn.commit()
    return run_ids


def insert_results(
    conn: sqlite3.Connection,
    run_id: str,
    quiz_id: str,
    model_id: str,
    rows: Iterable[dict],
) -> None:
    payload = []
    for row in rows:
        payload.append(
            (
                run_id,
                quiz_id,
                model_id,
                row.get("question_id", ""),
                row.get("choice", ""),
                row.get("reason", ""),
                row.get("additional_thoughts", ""),
                1 if row.get("refused") else 0,
                row.get("latency_ms"),
                row.get("tokens_in"),
                row.get("tokens_out"),
            )
        )
    if payload:
        conn.executemany(
            """
            INSERT INTO results
            (run_id, quiz_id, model_id, question_id, choice, reason, additional_thoughts, refused, latency_ms, tokens_in, tokens_out)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        conn.commit()


def insert_asset(conn: sqlite3.Connection, run_id: str, asset_type: str, path: Path) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO assets (run_id, asset_type, path, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (run_id, asset_type, str(path), created_at),
    )
    conn.commit()


def fetch_results(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT run_id, quiz_id, model_id, question_id, choice, reason, additional_thoughts,
               refused, latency_ms, tokens_in, tokens_out
        FROM results
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchall()
    return [dict(row) for row in rows]

def fetch_runs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT run_id, quiz_id, created_at, status, models_json, settings_json
        FROM runs
        ORDER BY created_at DESC
        """
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["models"] = json.loads(item.pop("models_json"))
        item["settings"] = json.loads(item.pop("settings_json"))
        items.append(item)
    return items


def fetch_run(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = conn.execute(
        """
        SELECT run_id, quiz_id, created_at, status, models_json, settings_json
        FROM runs
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["models"] = json.loads(item.pop("models_json"))
    item["settings"] = json.loads(item.pop("settings_json"))
    return item


def fetch_assets(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT run_id, asset_type, path, created_at
        FROM assets
        WHERE run_id = ?
        ORDER BY created_at DESC
        """,
        (run_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def delete_assets_for_run(conn: sqlite3.Connection, run_id: str) -> None:
    conn.execute("DELETE FROM assets WHERE run_id = ?", (run_id,))
    conn.commit()


def fetch_quiz_yaml(conn: sqlite3.Connection, quiz_id: str) -> str | None:
    row = conn.execute(
        "SELECT quiz_yaml FROM quizzes WHERE quiz_id = ?",
        (quiz_id,),
    ).fetchone()
    if not row:
        return None
    return row["quiz_yaml"]


def fetch_quizzes(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT quiz_id, title, source_json, raw_json, created_at
        FROM quizzes
        ORDER BY created_at DESC, quiz_id DESC
        """
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["source"] = json.loads(item.pop("source_json"))
        raw_payload = json.loads(item.pop("raw_json")) if row["raw_json"] else {}
        item["raw_available"] = bool(raw_payload)
        items.append(item)
    return items


def fetch_quiz_def(conn: sqlite3.Connection, quiz_id: str) -> dict | None:
    row = conn.execute(
        "SELECT quiz_yaml FROM quizzes WHERE quiz_id = ?",
        (quiz_id,),
    ).fetchone()
    if not row:
        return None
    return yaml.safe_load(row["quiz_yaml"])


def fetch_quiz_record(conn: sqlite3.Connection, quiz_id: str) -> dict | None:
    row = conn.execute(
        "SELECT quiz_yaml, raw_json FROM quizzes WHERE quiz_id = ?",
        (quiz_id,),
    ).fetchone()
    if not row:
        return None
    raw_payload = json.loads(row["raw_json"]) if row["raw_json"] else {}
    return {
        "quiz": yaml.safe_load(row["quiz_yaml"]),
        "quiz_yaml": row["quiz_yaml"],
        "raw_payload": raw_payload,
    }


def delete_quiz(conn: sqlite3.Connection, quiz_id: str) -> list[str]:
    run_rows = conn.execute(
        "SELECT run_id FROM runs WHERE quiz_id = ?",
        (quiz_id,),
    ).fetchall()
    run_ids = [row["run_id"] for row in run_rows]

    if run_ids:
        conn.executemany("DELETE FROM results WHERE run_id = ?", ((rid,) for rid in run_ids))
        conn.executemany("DELETE FROM assets WHERE run_id = ?", ((rid,) for rid in run_ids))
        conn.executemany("DELETE FROM runs WHERE run_id = ?", ((rid,) for rid in run_ids))

    conn.execute("DELETE FROM quizzes WHERE quiz_id = ?", (quiz_id,))
    conn.commit()
    return run_ids
