"""
SQLite storage. Plain sqlite3, no ORM.

Each table keeps the full object as JSON plus a few columns we filter on.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import config
from .schema import Autopsy, Trace


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS traces (
                id TEXT PRIMARY KEY,
                agent_name TEXT,
                status TEXT,
                source TEXT,
                created_at TEXT,
                data TEXT
            );
            CREATE TABLE IF NOT EXISTS autopsies (
                trace_id TEXT PRIMARY KEY,
                failure_class TEXT,
                root_tool TEXT,
                verified INTEGER,
                created_at TEXT,
                data TEXT
            );
            CREATE TABLE IF NOT EXISTS eval_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                data TEXT
            );
            """
        )


# ---------- traces ----------

def save_trace(trace: Trace):
    if not trace.created_at:
        trace.created_at = now()
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO traces VALUES (?, ?, ?, ?, ?, ?)",
            (trace.id, trace.agent_name, trace.status, trace.source,
             trace.created_at, trace.model_dump_json()),
        )


def get_trace(trace_id: str) -> Optional[Trace]:
    with connect() as conn:
        row = conn.execute("SELECT data FROM traces WHERE id = ?", (trace_id,)).fetchone()
    if row is None:
        return None
    return Trace.model_validate_json(row["data"])


def list_traces() -> list[Trace]:
    with connect() as conn:
        rows = conn.execute("SELECT data FROM traces ORDER BY created_at DESC, id").fetchall()
    return [Trace.model_validate_json(r["data"]) for r in rows]


def clear_all():
    with connect() as conn:
        conn.execute("DELETE FROM traces")
        conn.execute("DELETE FROM autopsies")


# ---------- autopsies ----------

def save_autopsy(autopsy: Autopsy, root_tool: str = ""):
    failure_class = autopsy.root_cause.failure_class if autopsy.root_cause else ""
    verified = 1 if (autopsy.replay and autopsy.replay.verified) else 0
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO autopsies VALUES (?, ?, ?, ?, ?, ?)",
            (autopsy.trace_id, failure_class, root_tool, verified,
             autopsy.created_at, autopsy.model_dump_json()),
        )


def get_autopsy(trace_id: str) -> Optional[Autopsy]:
    with connect() as conn:
        row = conn.execute("SELECT data FROM autopsies WHERE trace_id = ?", (trace_id,)).fetchone()
    if row is None:
        return None
    return Autopsy.model_validate_json(row["data"])


def list_autopsies() -> list[Autopsy]:
    with connect() as conn:
        rows = conn.execute("SELECT data FROM autopsies").fetchall()
    return [Autopsy.model_validate_json(r["data"]) for r in rows]


def autopsy_index() -> dict[str, dict]:
    """trace_id -> small summary, used for list pages."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT trace_id, failure_class, root_tool, verified FROM autopsies"
        ).fetchall()
    result = {}
    for r in rows:
        result[r["trace_id"]] = {
            "failure_class": r["failure_class"],
            "root_tool": r["root_tool"],
            "verified": bool(r["verified"]),
        }
    return result


# ---------- eval runs ----------

def save_eval_run(data: dict):
    with connect() as conn:
        conn.execute("INSERT INTO eval_runs (created_at, data) VALUES (?, ?)",
                     (now(), json.dumps(data)))


def latest_eval_run() -> Optional[dict]:
    with connect() as conn:
        row = conn.execute("SELECT created_at, data FROM eval_runs ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    data = json.loads(row["data"])
    data["created_at"] = row["created_at"]
    return data
