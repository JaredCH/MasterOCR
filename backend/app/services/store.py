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
    width_pt      REAL,
    height_pt     REAL,
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

-- ---------------------------------------------------------------------------
-- Phase 2: region capture
--
-- A layout is the set of regions on one page. Regions are stored as JSON on the
-- layout rather than as rows: they are always read and written together, they
-- are small, and keeping them in one column means a layout save is a single
-- atomic write with no ordering to get wrong.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS layouts (
    document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number   INTEGER NOT NULL,
    page_width_pt REAL NOT NULL DEFAULT 0,
    page_height_pt REAL NOT NULL DEFAULT 0,
    regions_json  TEXT NOT NULL DEFAULT '[]',
    updated_at    REAL NOT NULL,
    PRIMARY KEY (document_id, page_number)
);

CREATE TABLE IF NOT EXISTS region_runs (
    id            TEXT PRIMARY KEY,
    document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number   INTEGER NOT NULL,
    status        TEXT NOT NULL,
    error         TEXT,
    created_at    REAL NOT NULL,
    finished_at   REAL
);

CREATE INDEX IF NOT EXISTS idx_region_runs_document
    ON region_runs(document_id, page_number);

-- One row per (run, region, engine). `result_json` holds the normalized matrix
-- or text, so the comparison view never has to re-run anything.
CREATE TABLE IF NOT EXISTS region_results (
    run_id        TEXT NOT NULL REFERENCES region_runs(id) ON DELETE CASCADE,
    region_id     TEXT NOT NULL,
    engine_id     TEXT NOT NULL,
    status        TEXT NOT NULL,
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    result_json   TEXT,
    PRIMARY KEY (run_id, region_id, engine_id)
);

CREATE TABLE IF NOT EXISTS layout_templates (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    page_width_pt REAL NOT NULL DEFAULT 0,
    page_height_pt REAL NOT NULL DEFAULT 0,
    regions_json  TEXT NOT NULL DEFAULT '[]',
    created_at    REAL NOT NULL
);
"""


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            # Databases created before phase 2 lack the page dimension columns.
            # ALTER TABLE ADD COLUMN is idempotent-safe here because we probe
            # the schema first; SQLite has no IF NOT EXISTS for columns.
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(pages)").fetchall()
            }
            if "width_pt" not in columns:
                conn.execute("ALTER TABLE pages ADD COLUMN width_pt REAL")
            if "height_pt" not in columns:
                conn.execute("ALTER TABLE pages ADD COLUMN height_pt REAL")

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
                "text_chars, image_count, vector_paths, image_path, "
                "width_pt, height_pt) VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (
                        document_id,
                        page["number"],
                        page["classification"],
                        page["text_chars"],
                        page["image_count"],
                        page.get("vector_paths", 0),
                        page.get("image_path"),
                        page.get("width_pt"),
                        page.get("height_pt"),
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
    def expired_documents(self, cutoff: float) -> list[dict[str, Any]]:
        """Documents older than `cutoff`, with the paths needed to delete them."""
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT id, stored_path FROM documents WHERE created_at < ?",
                    (cutoff,),
                )
            ]

    def purge_older_than(self, cutoff: float) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM documents WHERE created_at < ?", (cutoff,)
            )
            return cursor.rowcount

    # -------------------------------------------------------------------
    # Phase 2: region layouts, runs, results, templates
    # -------------------------------------------------------------------

    # --- layouts ------------------------------------------------------
    def save_layout(
        self,
        document_id: str,
        page_number: int,
        *,
        page_width_pt: float,
        page_height_pt: float,
        regions: list[dict[str, Any]],
    ) -> None:
        """Replace the region set for one page in a single atomic write."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO layouts (document_id, page_number, page_width_pt, "
                "page_height_pt, regions_json, updated_at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(document_id, page_number) DO UPDATE SET "
                "page_width_pt=excluded.page_width_pt, "
                "page_height_pt=excluded.page_height_pt, "
                "regions_json=excluded.regions_json, updated_at=excluded.updated_at",
                (
                    document_id,
                    page_number,
                    page_width_pt,
                    page_height_pt,
                    json.dumps(regions, ensure_ascii=False),
                    time.time(),
                ),
            )

    def get_layout(
        self, document_id: str, page_number: int
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM layouts WHERE document_id = ? AND page_number = ?",
                (document_id, page_number),
            ).fetchone()
            if row is None:
                return None
            layout = dict(row)
            layout["regions"] = json.loads(layout.pop("regions_json") or "[]")
            return layout

    def delete_layout(self, document_id: str, page_number: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM layouts WHERE document_id = ? AND page_number = ?",
                (document_id, page_number),
            )
            return cursor.rowcount > 0

    # --- region runs --------------------------------------------------
    def create_region_run(
        self, document_id: str, page_number: int
    ) -> str:
        run_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO region_runs (id, document_id, page_number, status, "
                "created_at) VALUES (?,?,?,?,?)",
                (run_id, document_id, page_number, "running", time.time()),
            )
        return run_id

    def finish_region_run(
        self, run_id: str, *, status: str, error: str | None = None
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE region_runs SET status=?, error=?, finished_at=? WHERE id=?",
                (status, error, time.time(), run_id),
            )

    def get_region_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM region_runs WHERE id = ?", (run_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_region_runs(self, document_id: str, page_number: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM region_runs WHERE document_id = ? AND page_number = ? "
                    "ORDER BY created_at DESC",
                    (document_id, page_number),
                )
            ]

    # --- region results ------------------------------------------------
    def save_region_result(
        self,
        run_id: str,
        region_id: str,
        engine_id: str,
        *,
        status: str,
        duration_ms: int,
        error: str | None,
        result: dict[str, Any] | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO region_results (run_id, region_id, engine_id, "
                "status, duration_ms, error, result_json) VALUES (?,?,?,?,?,?,?)",
                (
                    run_id,
                    region_id,
                    engine_id,
                    status,
                    duration_ms,
                    error,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                ),
            )

    def get_region_results(self, run_id: str) -> list[dict[str, Any]]:
        """All results for a run, with result_json decoded."""
        with self._connect() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM region_results WHERE run_id = ? "
                    "ORDER BY region_id, engine_id",
                    (run_id,),
                )
            ]
        for row in rows:
            row["result"] = (
                json.loads(row.pop("result_json")) if row.get("result_json") else None
            )
        return rows

    def get_latest_region_results(self, document_id: str, page_number: int) -> list[dict[str, Any]]:
        """Results from the most recent finished run for a page."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM region_runs WHERE document_id = ? AND page_number = ? "
                "AND status IN ('ok','partial') ORDER BY created_at DESC LIMIT 1",
                (document_id, page_number),
            ).fetchone()
            if row is None:
                return []
            run_id = row["id"]
        return self.get_region_results(run_id)

    # --- templates -----------------------------------------------------
    def save_template(
        self,
        *,
        name: str,
        page_width_pt: float,
        page_height_pt: float,
        regions: list[dict[str, Any]],
        template_id: str | None = None,
    ) -> str:
        template_id = template_id or uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO layout_templates (id, name, page_width_pt, "
                "page_height_pt, regions_json, created_at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
                "page_width_pt=excluded.page_width_pt, "
                "page_height_pt=excluded.page_height_pt, "
                "regions_json=excluded.regions_json",
                (
                    template_id,
                    name,
                    page_width_pt,
                    page_height_pt,
                    json.dumps(regions, ensure_ascii=False),
                    time.time(),
                ),
            )
        return template_id

    def list_templates(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM layout_templates ORDER BY created_at DESC"
                )
            ]
        for row in rows:
            row["regions"] = json.loads(row.pop("regions_json") or "[]")
        return rows

    def get_template(self, template_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM layout_templates WHERE id = ?", (template_id,)
            ).fetchone()
            if row is None:
                return None
            template = dict(row)
            template["regions"] = json.loads(template.pop("regions_json") or "[]")
            return template

    def delete_template(self, template_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM layout_templates WHERE id = ?", (template_id,)
            )
            return cursor.rowcount > 0
