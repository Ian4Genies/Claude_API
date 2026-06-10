import sqlite3
import time
from pathlib import Path


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            recipe_name TEXT,
            status TEXT,
            started_at REAL,
            finished_at REAL,
            total INT DEFAULT 0,
            succeeded INT DEFAULT 0,
            failed INT DEFAULT 0,
            skipped INT DEFAULT 0,
            input_tokens INT DEFAULT 0,
            output_tokens INT DEFAULT 0,
            cache_read_tokens INT DEFAULT 0,
            cost_usd REAL DEFAULT 0,
            manifest_path TEXT
        );
        CREATE TABLE IF NOT EXISTS job_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT,
            pair_key TEXT,
            status TEXT,
            error TEXT,
            output_path TEXT,
            duration_s REAL DEFAULT 0,
            input_tokens INT DEFAULT 0,
            output_tokens INT DEFAULT 0,
            cache_read_tokens INT DEFAULT 0,
            cost_usd REAL DEFAULT 0
        );
    """)
    return conn


class JobHistory:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn = _connect(db_path)

    def start_job(self, job_id: str, recipe_name: str) -> None:
        self._conn.execute(
            "INSERT INTO jobs (id, recipe_name, status, started_at) VALUES (?, ?, ?, ?)",
            (job_id, recipe_name, "running", time.time()),
        )
        self._conn.commit()

    def add_item(self, job_id: str, item: dict) -> None:
        self._conn.execute(
            """INSERT INTO job_items
               (job_id, pair_key, status, error, output_path, duration_s,
                input_tokens, output_tokens, cache_read_tokens, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                item["pair_key"],
                item["status"],
                item.get("error"),
                item.get("output_path"),
                item.get("duration_s", 0),
                item.get("input_tokens", 0),
                item.get("output_tokens", 0),
                item.get("cache_read_input_tokens", 0),
                item.get("cost_usd", 0),
            ),
        )
        self._conn.commit()

    def finish_job(self, job_id: str, summary: dict, manifest_path: str) -> None:
        self._conn.execute(
            """UPDATE jobs SET status=?, finished_at=?, total=?, succeeded=?, failed=?,
               skipped=?, input_tokens=?, output_tokens=?, cache_read_tokens=?,
               cost_usd=?, manifest_path=? WHERE id=?""",
            (
                summary.get("status", "done"),
                time.time(),
                summary.get("total", 0),
                summary.get("succeeded", 0),
                summary.get("failed", 0),
                summary.get("skipped", 0),
                summary.get("input_tokens", 0),
                summary.get("output_tokens", 0),
                summary.get("cache_read_input_tokens", 0),
                summary.get("cost_usd", 0),
                manifest_path,
                job_id,
            ),
        )
        self._conn.commit()

    def abandon_running(self, recipe_name: str) -> None:
        self._conn.execute(
            "UPDATE jobs SET status='aborted', finished_at=? WHERE recipe_name=? AND status='running'",
            (time.time(), recipe_name),
        )
        self._conn.commit()

    def failed_keys(self, recipe_name: str) -> list[str]:
        row = self._conn.execute(
            """SELECT id FROM jobs WHERE recipe_name=? AND status='done' AND failed > 0
               ORDER BY finished_at DESC LIMIT 1""",
            (recipe_name,),
        ).fetchone()
        if not row:
            return []
        rows = self._conn.execute(
            "SELECT pair_key FROM job_items WHERE job_id=? AND status='error'",
            (row["id"],),
        ).fetchall()
        return [r["pair_key"] for r in rows]

    def get_job(self, job_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        items = self._conn.execute(
            "SELECT * FROM job_items WHERE job_id=? ORDER BY id", (job_id,)
        ).fetchall()
        return {"job": dict(row), "items": [dict(i) for i in items]}
