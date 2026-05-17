"""SQLite local cache — mirrors assets, crawl_runs, lineage_jobs for fast UI reads."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

CACHE_DIR = Path(".cache")
DB_PATH = CACHE_DIR / "index.db"

_DDL = """
CREATE TABLE IF NOT EXISTS assets (
    asset_id     TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    kind         TEXT NOT NULL,
    identifier   TEXT NOT NULL,
    repo_url     TEXT,
    branch       TEXT,
    commit_sha   TEXT,
    content_hash TEXT NOT NULL,
    size_bytes   INTEGER,
    raw_path     TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crawl_runs (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT,
    finished_at TEXT,
    sources     TEXT,
    stats       TEXT,
    status      TEXT,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS lineage_jobs (
    job_id      TEXT PRIMARY KEY,
    asset_id    TEXT,
    status      TEXT,
    schema_kind TEXT,
    llm_model   TEXT,
    started_at  TEXT,
    finished_at TEXT,
    error       TEXT,
    input_hash  TEXT
);
"""


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# assets
# ---------------------------------------------------------------------------

def upsert_asset(asset: dict, db_path: Path = DB_PATH) -> str:
    """Insert, update (hash changed), or skip (hash unchanged). Returns 'inserted'/'updated'/'skipped'."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT content_hash FROM assets WHERE asset_id = ?", (asset["asset_id"],)
        ).fetchone()

        if row is None:
            row_data = {**asset}
            row_data.setdefault("created_at", _now())
            row_data.setdefault("updated_at", _now())
            conn.execute(
                """INSERT INTO assets
                   (asset_id, source, kind, identifier, repo_url, branch, commit_sha,
                    content_hash, size_bytes, raw_path, created_at, updated_at)
                   VALUES
                   (:asset_id, :source, :kind, :identifier, :repo_url, :branch, :commit_sha,
                    :content_hash, :size_bytes, :raw_path, :created_at, :updated_at)""",
                row_data,
            )
            return "inserted"

        if row["content_hash"] == asset["content_hash"]:
            return "skipped"

        conn.execute(
            """UPDATE assets SET
               source=:source, kind=:kind, identifier=:identifier, repo_url=:repo_url,
               branch=:branch, commit_sha=:commit_sha, content_hash=:content_hash,
               size_bytes=:size_bytes, raw_path=:raw_path, updated_at=:updated_at
               WHERE asset_id=:asset_id""",
            {**asset, "updated_at": _now()},
        )
        return "updated"


def get_asset(asset_id: str, db_path: Path = DB_PATH) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        return dict(row) if row else None


def list_assets(filters: dict | None = None, db_path: Path = DB_PATH) -> list[dict]:
    filters = filters or {}
    query = "SELECT * FROM assets"
    params: list = []
    if filters:
        clauses = [f"{k} = ?" for k in filters]
        query += " WHERE " + " AND ".join(clauses)
        params = list(filters.values())
    with _connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# crawl_runs
# ---------------------------------------------------------------------------

def upsert_crawl_run(run: dict, db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO crawl_runs (run_id, started_at, finished_at, sources, stats, status, error)
               VALUES (:run_id, :started_at, :finished_at, :sources, :stats, :status, :error)
               ON CONFLICT(run_id) DO UPDATE SET
               finished_at=excluded.finished_at, sources=excluded.sources,
               stats=excluded.stats, status=excluded.status, error=excluded.error""",
            run,
        )


def get_crawl_run(run_id: str, db_path: Path = DB_PATH) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM crawl_runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None


def list_crawl_runs(db_path: Path = DB_PATH) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM crawl_runs ORDER BY started_at DESC").fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# lineage_jobs
# ---------------------------------------------------------------------------

def upsert_lineage_job(job: dict, db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO lineage_jobs
               (job_id, asset_id, status, schema_kind, llm_model, started_at, finished_at, error, input_hash)
               VALUES
               (:job_id, :asset_id, :status, :schema_kind, :llm_model, :started_at, :finished_at, :error, :input_hash)
               ON CONFLICT(job_id) DO UPDATE SET
               asset_id=excluded.asset_id, status=excluded.status, schema_kind=excluded.schema_kind,
               llm_model=excluded.llm_model, started_at=excluded.started_at,
               finished_at=excluded.finished_at, error=excluded.error, input_hash=excluded.input_hash""",
            job,
        )


def get_lineage_job(job_id: str, db_path: Path = DB_PATH) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM lineage_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_lineage_jobs(asset_id: str | None = None, db_path: Path = DB_PATH) -> list[dict]:
    with _connect(db_path) as conn:
        if asset_id:
            rows = conn.execute(
                "SELECT * FROM lineage_jobs WHERE asset_id = ?", (asset_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM lineage_jobs").fetchall()
        return [dict(r) for r in rows]
