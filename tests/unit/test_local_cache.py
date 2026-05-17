"""Unit tests for SQLite local cache — M2 acceptance criteria."""

from pathlib import Path

import pytest

from app.storage.local_cache import (
    get_asset,
    get_crawl_run,
    get_lineage_job,
    list_assets,
    list_lineage_jobs,
    upsert_asset,
    upsert_crawl_run,
    upsert_lineage_job,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path: Path) -> Path:
    """Isolated SQLite DB for each test."""
    return tmp_path / "index.db"


def _asset(asset_id: str = "a1", content_hash: str = "hash_v1") -> dict:
    return {
        "asset_id": asset_id,
        "source": "git",
        "kind": "sql_file",
        "identifier": "sql/query.sql",
        "repo_url": "https://github.com/org/repo",
        "branch": "main",
        "commit_sha": "abc123",
        "content_hash": content_hash,
        "size_bytes": 512,
        "raw_path": ".cache/a1.sql",
    }


# ---------------------------------------------------------------------------
# Asset upsert — M2 acceptance criteria
# ---------------------------------------------------------------------------

def test_insert_new_asset(db: Path):
    """Acceptance: insert new asset returns 'inserted' and the row is retrievable."""
    result = upsert_asset(_asset(), db_path=db)
    assert result == "inserted"

    row = get_asset("a1", db_path=db)
    assert row is not None
    assert row["identifier"] == "sql/query.sql"
    assert row["content_hash"] == "hash_v1"
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


def test_update_on_hash_change(db: Path):
    """Acceptance: update on hash change returns 'updated' and stores new hash."""
    upsert_asset(_asset(content_hash="hash_v1"), db_path=db)
    result = upsert_asset(_asset(content_hash="hash_v2"), db_path=db)
    assert result == "updated"

    row = get_asset("a1", db_path=db)
    assert row["content_hash"] == "hash_v2"


def test_noop_on_hash_match(db: Path):
    """Acceptance: no-op on hash match returns 'skipped' and row is unchanged."""
    upsert_asset(_asset(content_hash="hash_v1"), db_path=db)
    first_row = get_asset("a1", db_path=db)

    result = upsert_asset(_asset(content_hash="hash_v1"), db_path=db)
    assert result == "skipped"

    second_row = get_asset("a1", db_path=db)
    assert second_row["updated_at"] == first_row["updated_at"]


# ---------------------------------------------------------------------------
# Asset listing
# ---------------------------------------------------------------------------

def test_list_assets_returns_all(db: Path):
    upsert_asset(_asset("a1"), db_path=db)
    upsert_asset(_asset("a2"), db_path=db)
    assets = list_assets(db_path=db)
    assert len(assets) == 2


def test_list_assets_with_filter(db: Path):
    upsert_asset({**_asset("a1"), "source": "git"}, db_path=db)
    upsert_asset({**_asset("a2"), "source": "bigquery"}, db_path=db)
    git_assets = list_assets(filters={"source": "git"}, db_path=db)
    assert len(git_assets) == 1
    assert git_assets[0]["asset_id"] == "a1"


def test_list_assets_empty(db: Path):
    assert list_assets(db_path=db) == []


# ---------------------------------------------------------------------------
# crawl_runs
# ---------------------------------------------------------------------------

def test_upsert_crawl_run_insert_and_update(db: Path):
    run = {
        "run_id": "r1",
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": None,
        "sources": '["git"]',
        "stats": "{}",
        "status": "running",
        "error": None,
    }
    upsert_crawl_run(run, db_path=db)
    assert get_crawl_run("r1", db_path=db)["status"] == "running"

    run["status"] = "succeeded"
    run["finished_at"] = "2026-01-01T00:01:00+00:00"
    upsert_crawl_run(run, db_path=db)
    assert get_crawl_run("r1", db_path=db)["status"] == "succeeded"


# ---------------------------------------------------------------------------
# lineage_jobs
# ---------------------------------------------------------------------------

def test_upsert_lineage_job_insert_and_update(db: Path):
    job = {
        "job_id": "j1",
        "asset_id": "a1",
        "status": "queued",
        "schema_kind": "stm",
        "llm_model": "gpt-4o",
        "started_at": None,
        "finished_at": None,
        "error": None,
        "input_hash": "hash_v1",
    }
    upsert_lineage_job(job, db_path=db)
    assert get_lineage_job("j1", db_path=db)["status"] == "queued"

    job["status"] = "succeeded"
    job["finished_at"] = "2026-01-01T00:05:00+00:00"
    upsert_lineage_job(job, db_path=db)
    assert get_lineage_job("j1", db_path=db)["status"] == "succeeded"


def test_list_lineage_jobs_by_asset(db: Path):
    job_a = {
        "job_id": "j1", "asset_id": "a1", "status": "succeeded",
        "schema_kind": "stm", "llm_model": "gpt-4o",
        "started_at": None, "finished_at": None, "error": None, "input_hash": "h1",
    }
    job_b = {
        "job_id": "j2", "asset_id": "a2", "status": "queued",
        "schema_kind": "stm", "llm_model": "gpt-4o",
        "started_at": None, "finished_at": None, "error": None, "input_hash": "h2",
    }
    upsert_lineage_job(job_a, db_path=db)
    upsert_lineage_job(job_b, db_path=db)

    assert len(list_lineage_jobs(db_path=db)) == 2
    assert len(list_lineage_jobs(asset_id="a1", db_path=db)) == 1
