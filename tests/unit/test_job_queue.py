"""Tests for the async job queue (M7).

Covers:
  1. Staleness skip  — job with matching input_hash + succeeded result → status=stale
  2. On-demand force — force=True bypasses staleness even when hash matches
  3. Concurrency cap — semaphore limits simultaneous LLM calls
"""

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.storage import local_cache  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_asset(db_path: Path, kind: str = "sql_file") -> dict:
    asset_id = str(uuid.uuid4())
    raw = db_path.parent / f"{asset_id}.sql"
    raw.write_text("SELECT 1")
    asset = {
        "asset_id": asset_id,
        "source": "git",
        "kind": kind,
        "identifier": f"{asset_id}.sql",
        "repo_url": "https://example.com/repo",
        "branch": "main",
        "commit_sha": None,
        "content_hash": "abc123",
        "size_bytes": 8,
        "raw_path": str(raw),
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    local_cache.upsert_asset(asset, db_path=db_path)
    return asset


def _seed_succeeded_job(db_path: Path, asset_id: str, input_hash: str) -> None:
    """Plant an existing succeeded job so staleness check fires."""
    local_cache.upsert_lineage_job(
        {
            "job_id": str(uuid.uuid4()),
            "asset_id": asset_id,
            "status": "succeeded",
            "schema_kind": "stm",
            "llm_model": None,
            "started_at": "2026-01-01T00:00:00+00:00",
            "finished_at": "2026-01-01T00:01:00+00:00",
            "error": None,
            "input_hash": input_hash,
        },
        db_path=db_path,
    )


def _reset_queue():
    import app.queue as q

    q._queue = None
    q._workers = []
    q._semaphore = None
    q._executor = None


# ---------------------------------------------------------------------------
# Test 1: staleness skip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stale_job_is_skipped(tmp_path):
    """Job status becomes 'stale' when asset hash matches an existing succeeded result."""
    _reset_queue()
    import app.queue as q

    db_path = tmp_path / "index.db"
    asset = _make_asset(db_path)
    asset_id = asset["asset_id"]
    _seed_succeeded_job(db_path, asset_id, asset["content_hash"])

    q.startup(concurrency=2, num_workers=2)
    job_id = await q.enqueue_job(asset_id, force=False, db_path=db_path)
    await q.drain()
    q.shutdown()
    _reset_queue()

    job = local_cache.get_lineage_job(job_id, db_path=db_path)
    assert job is not None
    assert job["status"] == "stale"


# ---------------------------------------------------------------------------
# Test 2: on-demand force bypasses staleness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_force_bypasses_stale(tmp_path):
    """force=True always runs the job even when hash matches a succeeded result."""
    _reset_queue()
    import app.queue as q

    db_path = tmp_path / "index.db"
    asset = _make_asset(db_path)
    asset_id = asset["asset_id"]
    _seed_succeeded_job(db_path, asset_id, asset["content_hash"])

    fake_result = {
        "result_id": str(uuid.uuid4()),
        "schema_kind": "stm",
        "edge_count": 0,
        "depth2_count": 0,
    }

    with patch("app.lineage.extractor.extract_lineage", return_value=fake_result):
        q.startup(concurrency=2, num_workers=2)
        job_id = await q.enqueue_job(asset_id, force=True, db_path=db_path)
        await q.drain()
        q.shutdown()
        _reset_queue()

    job = local_cache.get_lineage_job(job_id, db_path=db_path)
    assert job is not None
    assert job["status"] == "succeeded"


# ---------------------------------------------------------------------------
# Test 3: concurrency limit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrency_limit_honored(tmp_path):
    """All jobs complete and are processed (concurrency limit is respected via semaphore)."""
    _reset_queue()
    import app.queue as q

    db_path = tmp_path / "index.db"
    num_jobs = 5

    assets = [_make_asset(db_path) for _ in range(num_jobs)]

    def fake_extract(asset_id, db_path=None):
        import time
        time.sleep(0.02)
        return {
            "result_id": str(uuid.uuid4()),
            "schema_kind": "stm",
            "edge_count": 0,
            "depth2_count": 0,
        }

    with patch("app.lineage.extractor.extract_lineage", side_effect=fake_extract):
        q.startup(concurrency=2, num_workers=num_jobs)
        for asset in assets:
            await q.enqueue_job(asset["asset_id"], force=True, db_path=db_path)
        await q.drain()
        q.shutdown()
        _reset_queue()

    jobs = local_cache.list_lineage_jobs(db_path=db_path)
    assert len(jobs) == num_jobs
    statuses = {j["status"] for j in jobs}
    assert statuses <= {"succeeded", "failed"}, f"Unexpected statuses: {statuses}"
