"""SQLite persistence.

One file on the Railway volume. WAL mode so the SSE progress reader and the
worker writer never block each other.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,
    filename      TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    page_count    INTEGER NOT NULL,
    classification TEXT NOT NULL,
    stored_path   TEXT NOT NULL,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS pages (
    document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number   INTEGER NOT NULL,
    classification TEXT NOT NULL,
    text_chars    INTEGER NOT NULL,
    image_count   INTEGER NOT NULL,
    vector_paths  INTEGER NOT NULL DEFAULT 0,
    image_path    TEXT,
    PRIMARY KEY (document_id, page_number)
);

CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    engine_id     TEXT NOT NULL,
    status        TEXT NOT NULL,
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    meta_json     TEXT,
    created_at    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_document ON runs(document_id);

CREATE TABLE IF NOT EXISTS results (
    run_id        TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    page_number   INTEGER NOT NULL,
    text          TEXT,
    markdown      TEXT,
    html          TEXT,
    blocks_json   TEXT,
    confidence    REAL,
    PRIMARY KEY (run_id, page_number)
);

CREATE TABLE IF NOT EXISTS metrics (
    run_id        TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    cer           REAL,
    wer           REAL,
    reference     TEXT,
    hallucination_json TEXT,
    dimension_json     TEXT,
    table_json         TEXT
);

CREATE TABLE IF NOT EXISTS scores (
    document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    engine_id     TEXT NOT NULL,
    stars         INTEGER NOT NULL,
    notes         TEXT,
    updated_at    REAL NOT NULL,
    PRIMARY KEY (document_id, engine_id)
);

CREATE TABLE IF NOT EXISTS quota (
    engine_id     TEXT NOT NULL,
    period        TEXT NOT NULL,
    used          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (engine_id, period)
);
"""


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- documents ----------------------------------------------------
    def create_document(
        self,
        *,
        filename: str,
        size_bytes: int,
        page_count: int,
        classification: str,
        stored_path: str,
        pages: list[dict[str, Any]],
        document_id: str | None = None,
    ) -> str:
        document_id = document_id or uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO documents (id, filename, size_bytes, page_count, "
                "classification, stored_path, created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    document_id,
                    filename,
                    size_bytes,
                    page_count,
                    classification,
                    stored_path,
                    time.time(),
                ),
            )
            conn.executemany(
                "INSERT INTO pages (document_id, page_number, classification, "
                "text_chars, image_count, vector_paths, image_path) "
                "VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        document_id,
                        page["number"],
                        page["classification"],
                        page["text_chars"],
                        page["image_count"],
                        page.get("vector_paths", 0),
                        page.get("image_path"),
                    )
                    for page in pages
                ],
            )
        return document_id

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            if row is None:
                return None
            document = dict(row)
            document["pages"] = [
                dict(page)
                for page in conn.execute(
                    "SELECT * FROM pages WHERE document_id = ? ORDER BY page_number",
                    (document_id,),
                )
            ]
            return document

    def list_documents(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM documents ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            ]

    # --- runs ---------------------------------------------------------
    def create_run(self, document_id: str, engine_id: str) -> str:
        run_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, document_id, engine_id, status, created_at) "
                "VALUES (?,?,?,?,?)",
                (run_id, document_id, engine_id, "pending", time.time()),
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        duration_ms: int,
        error: str | None,
        meta: dict[str, Any] | None,
        pages: list[dict[str, Any]],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET status=?, duration_ms=?, error=?, meta_json=? WHERE id=?",
                (status, duration_ms, error, json.dumps(meta or {}), run_id),
            )
            conn.executemany(
                "INSERT OR REPLACE INTO results (run_id, page_number, text, markdown, "
                "html, blocks_json, confidence) VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        run_id,
                        page.get("page", index + 1),
                        page.get("text"),
                        page.get("markdown"),
                        page.get("html"),
                        json.dumps(page.get("blocks") or []),
                        page.get("confidence"),
                    )
                    for index, page in enumerate(pages)
                ],
            )

    def get_runs(self, document_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            runs = [dict(row) for row in conn.execute(
                "SELECT * FROM runs WHERE document_id = ? ORDER BY created_at",
                (document_id,),
            )]
            for run in runs:
                run["pages"] = [
                    dict(page)
                    for page in conn.execute(
                        "SELECT * FROM results WHERE run_id = ? ORDER BY page_number",
                        (run["id"],),
                    )
                ]
                run["metrics"] = self._get_metrics(conn, run["id"])
            return runs

    def _get_metrics(self, conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM metrics WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        metrics = dict(row)
        # Expose the JSON columns under the same names the metrics module and
        # the frontend use, so there is one vocabulary across the stack.
        for column, key in (
            ("hallucination_json", "hallucination"),
            ("dimension_json", "dimensions"),
            ("table_json", "tables"),
        ):
            if metrics.get(column):
                metrics[key] = json.loads(metrics[column])
        return metrics

    def save_metrics(self, run_id: str, metrics: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO metrics (run_id, cer, wer, reference, "
                "hallucination_json, dimension_json, table_json) VALUES (?,?,?,?,?,?,?)",
                (
                    run_id,
                    metrics.get("cer"),
                    metrics.get("wer"),
                    metrics.get("reference"),
                    json.dumps(metrics.get("hallucination") or {}),
                    json.dumps(metrics.get("dimensions") or {}),
                    json.dumps(metrics.get("tables") or {}),
                ),
            )

    # --- human scores -------------------------------------------------
    def save_score(
        self, document_id: str, engine_id: str, stars: int, notes: str | None
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scores (document_id, engine_id, stars, notes, "
                "updated_at) VALUES (?,?,?,?,?)",
                (document_id, engine_id, stars, notes, time.time()),
            )

    def get_scores(self, document_id: str) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            return {
                row["engine_id"]: dict(row)
                for row in conn.execute(
                    "SELECT * FROM scores WHERE document_id = ?", (document_id,)
                )
            }

    # --- quota ledger -------------------------------------------------
    def quota_used(self, engine_id: str, period: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT used FROM quota WHERE engine_id = ? AND period = ?",
                (engine_id, period),
            ).fetchone()
            return int(row["used"]) if row else 0

    def quota_increment(self, engine_id: str, period: str, amount: int = 1) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO quota (engine_id, period, used) VALUES (?,?,?) "
                "ON CONFLICT(engine_id, period) DO UPDATE SET used = used + ?",
                (engine_id, period, amount, amount),
            )

    # --- retention ----------------------------------------------------
    def purge_older_than(self, cutoff: float) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM documents WHERE created_at < ?", (cutoff,)
            )
            return cursor.rowcount
