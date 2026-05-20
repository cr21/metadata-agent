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

CREATE TABLE IF NOT EXISTS lineage_results (
    result_id   TEXT PRIMARY KEY,
    asset_id    TEXT NOT NULL,
    job_id      TEXT,
    schema_kind TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lineage_edges (
    edge_id             TEXT PRIMARY KEY,
    source_asset_id     TEXT NOT NULL,
    target_table        TEXT NOT NULL,
    target_column       TEXT NOT NULL,
    source_table        TEXT NOT NULL,
    source_column       TEXT NOT NULL,
    transformation_type TEXT,
    transformation      TEXT,
    depth               INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_calls (
    call_id           TEXT PRIMARY KEY,
    asset_id          TEXT,
    kind              TEXT,
    model             TEXT NOT NULL,
    attempt           INTEGER NOT NULL DEFAULT 1,
    system_prompt     TEXT NOT NULL,
    user_prompt       TEXT NOT NULL,
    raw_output        TEXT NOT NULL,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    total_tokens      INTEGER,
    usd_cost          REAL,
    duration_ms       INTEGER,
    created_at        TEXT NOT NULL
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


# ---------------------------------------------------------------------------
# lineage_results
# ---------------------------------------------------------------------------

def upsert_lineage_result(result: dict, db_path: Path = DB_PATH) -> None:
    """Insert lineage result. Idempotent — existing result_id is a no-op."""
    row = {**result}
    row.setdefault("created_at", _now())
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO lineage_results
               (result_id, asset_id, job_id, schema_kind, payload, created_at)
               VALUES (:result_id, :asset_id, :job_id, :schema_kind, :payload, :created_at)""",
            row,
        )


def get_lineage_result(result_id: str, db_path: Path = DB_PATH) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM lineage_results WHERE result_id = ?", (result_id,)
        ).fetchone()
        return dict(row) if row else None


def list_lineage_results(asset_id: str | None = None, db_path: Path = DB_PATH) -> list[dict]:
    with _connect(db_path) as conn:
        if asset_id:
            rows = conn.execute(
                "SELECT * FROM lineage_results WHERE asset_id = ? ORDER BY created_at DESC",
                (asset_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM lineage_results ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# lineage_edges
# ---------------------------------------------------------------------------

def upsert_lineage_edge(edge: dict, db_path: Path = DB_PATH) -> None:
    """Insert a lineage edge. Idempotent — existing edge_id is a no-op."""
    row = {**edge}
    row.setdefault("created_at", _now())
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO lineage_edges
               (edge_id, source_asset_id, target_table, target_column,
                source_table, source_column, transformation_type, transformation,
                depth, created_at)
               VALUES
               (:edge_id, :source_asset_id, :target_table, :target_column,
                :source_table, :source_column, :transformation_type, :transformation,
                :depth, :created_at)""",
            row,
        )


def list_lineage_edges(
    source_asset_id: str | None = None,
    depth: int | None = None,
    db_path: Path = DB_PATH,
) -> list[dict]:
    with _connect(db_path) as conn:
        clauses, params = [], []
        if source_asset_id:
            clauses.append("source_asset_id = ?")
            params.append(source_asset_id)
        if depth is not None:
            clauses.append("depth = ?")
            params.append(depth)
        sql = "SELECT * FROM lineage_edges"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# llm_calls
# ---------------------------------------------------------------------------

def log_llm_call(call: dict, db_path: Path = DB_PATH) -> None:
    """Persist one LLM call record. Idempotent on call_id."""
    row = {**call}
    row.setdefault("created_at", _now())
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO llm_calls
               (call_id, asset_id, kind, model, attempt,
                system_prompt, user_prompt, raw_output,
                prompt_tokens, completion_tokens, total_tokens,
                usd_cost, duration_ms, created_at)
               VALUES
               (:call_id, :asset_id, :kind, :model, :attempt,
                :system_prompt, :user_prompt, :raw_output,
                :prompt_tokens, :completion_tokens, :total_tokens,
                :usd_cost, :duration_ms, :created_at)""",
            row,
        )


def list_llm_calls(
    asset_id: str | None = None,
    limit: int = 100,
    db_path: Path = DB_PATH,
) -> list[dict]:
    with _connect(db_path) as conn:
        if asset_id:
            rows = conn.execute(
                "SELECT * FROM llm_calls WHERE asset_id = ? ORDER BY created_at DESC LIMIT ?",
                (asset_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM llm_calls ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_llm_call_stats(db_path: Path = DB_PATH) -> dict:
    """Return aggregate totals across all recorded LLM calls."""
    with _connect(db_path) as conn:
        row = conn.execute(
            """SELECT
                COUNT(*)            AS total_calls,
                COALESCE(SUM(total_tokens), 0)      AS total_tokens,
                COALESCE(SUM(prompt_tokens), 0)     AS total_prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS total_completion_tokens,
                COALESCE(SUM(usd_cost), 0.0)        AS total_usd,
                COALESCE(AVG(duration_ms), 0.0)     AS avg_duration_ms
               FROM llm_calls"""
        ).fetchone()
        return dict(row) if row else {}
