"""Async lineage job queue — in-process asyncio workers with bounded semaphore."""

import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from app.storage import local_cache

logger = logging.getLogger(__name__)

_queue: asyncio.Queue | None = None
_workers: list[asyncio.Task] = []
_semaphore: asyncio.Semaphore | None = None
_executor: ThreadPoolExecutor | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_queue() -> asyncio.Queue:
    if _queue is None:
        raise RuntimeError("Job queue not started — call startup() first.")
    return _queue


async def enqueue_job(
    asset_id: str,
    force: bool = False,
    db_path: Path = local_cache.DB_PATH,
) -> str:
    """Create a lineage_jobs row and put it on the queue. Returns job_id."""
    job_id = str(uuid.uuid4())
    asset = local_cache.get_asset(asset_id, db_path=db_path)
    if asset is None:
        raise ValueError(f"Asset not found: {asset_id}")

    content_hash = asset["content_hash"]

    local_cache.upsert_lineage_job(
        {
            "job_id": job_id,
            "asset_id": asset_id,
            "status": "queued",
            "schema_kind": None,
            "llm_model": None,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "input_hash": content_hash,
        },
        db_path=db_path,
    )

    await get_queue().put({"job_id": job_id, "asset_id": asset_id, "force": force, "db_path": db_path})
    logger.info("Enqueued job %s for asset %s (force=%s)", job_id, asset_id, force)
    return job_id


async def drain() -> None:
    """Wait until the queue is empty and all jobs have finished."""
    q = get_queue()
    await q.join()


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

async def _worker(worker_id: int) -> None:
    assert _semaphore is not None
    assert _executor is not None
    q = get_queue()

    while True:
        item = await q.get()
        job_id: str = item["job_id"]
        asset_id: str = item["asset_id"]
        force: bool = item["force"]
        db_path: Path = item["db_path"]

        try:
            await _process_job(job_id, asset_id, force, db_path)
        except Exception:
            logger.exception("Worker %d: unhandled error on job %s", worker_id, job_id)
        finally:
            q.task_done()


async def _process_job(
    job_id: str,
    asset_id: str,
    force: bool,
    db_path: Path,
) -> None:
    assert _semaphore is not None
    assert _executor is not None

    asset = local_cache.get_asset(asset_id, db_path=db_path)
    if asset is None:
        _fail_job(job_id, "Asset not found", db_path)
        return

    content_hash = asset["content_hash"]

    # Staleness check — skip unless forced
    if not force:
        if _is_stale(asset_id, content_hash, db_path):
            local_cache.upsert_lineage_job(
                {
                    "job_id": job_id,
                    "asset_id": asset_id,
                    "status": "stale",
                    "schema_kind": None,
                    "llm_model": None,
                    "started_at": _now(),
                    "finished_at": _now(),
                    "error": None,
                    "input_hash": content_hash,
                },
                db_path=db_path,
            )
            logger.info("Job %s stale — skipping (hash match + succeeded result)", job_id)
            return

    local_cache.upsert_lineage_job(
        {
            "job_id": job_id,
            "asset_id": asset_id,
            "status": "running",
            "schema_kind": None,
            "llm_model": None,
            "started_at": _now(),
            "finished_at": None,
            "error": None,
            "input_hash": content_hash,
        },
        db_path=db_path,
    )

    async with _semaphore:
        loop = asyncio.get_running_loop()
        try:
            from app.lineage.extractor import extract_lineage  # avoid circular at import time
            result = await loop.run_in_executor(
                _executor,
                lambda: extract_lineage(asset_id, db_path=db_path),
            )
            local_cache.upsert_lineage_job(
                {
                    "job_id": job_id,
                    "asset_id": asset_id,
                    "status": "succeeded",
                    "schema_kind": result["schema_kind"],
                    "llm_model": None,
                    "started_at": None,
                    "finished_at": _now(),
                    "error": None,
                    "input_hash": content_hash,
                },
                db_path=db_path,
            )
            logger.info("Job %s succeeded for asset %s", job_id, asset_id)
        except Exception as exc:
            _fail_job(job_id, str(exc), db_path, asset_id=asset_id, input_hash=content_hash)
            logger.exception("Job %s failed for asset %s", job_id, asset_id)


def _is_stale(asset_id: str, content_hash: str, db_path: Path) -> bool:
    """Return True if a non-failed result exists for this asset with the same input_hash."""
    jobs = local_cache.list_lineage_jobs(asset_id=asset_id, db_path=db_path)
    for job in jobs:
        if (
            job["input_hash"] == content_hash
            and job["status"] in ("succeeded",)
        ):
            return True
    return False


def _fail_job(
    job_id: str,
    error: str,
    db_path: Path,
    asset_id: str = "",
    input_hash: str = "",
) -> None:
    local_cache.upsert_lineage_job(
        {
            "job_id": job_id,
            "asset_id": asset_id,
            "status": "failed",
            "schema_kind": None,
            "llm_model": None,
            "started_at": None,
            "finished_at": _now(),
            "error": error,
            "input_hash": input_hash,
        },
        db_path=db_path,
    )


# ---------------------------------------------------------------------------
# Lifecycle — called from FastAPI lifespan
# ---------------------------------------------------------------------------

def startup(concurrency: int = 4, num_workers: int = 4) -> None:
    """Start the queue and background worker tasks. Call once at app startup."""
    global _queue, _semaphore, _executor, _workers

    # Mark any jobs left in 'running' state from a previous server process as failed.
    # They are orphaned — the executor that was running them is gone.
    _recover_orphaned_jobs()

    _queue = asyncio.Queue()
    _semaphore = asyncio.Semaphore(concurrency)
    _executor = ThreadPoolExecutor(max_workers=num_workers, thread_name_prefix="lineage-worker")
    _workers = [
        asyncio.ensure_future(_worker(i)) for i in range(num_workers)
    ]
    logger.info("Job queue started (concurrency=%d, workers=%d)", concurrency, num_workers)


def _recover_orphaned_jobs() -> None:
    """Mark any 'running' jobs as failed — they were orphaned by a previous server crash/restart."""
    jobs = local_cache.list_lineage_jobs()
    orphans = [j for j in jobs if j.get("status") == "running"]
    if not orphans:
        return
    logger.warning("Recovering %d orphaned 'running' jobs from previous process", len(orphans))
    for job in orphans:
        local_cache.upsert_lineage_job({
            **job,
            "status": "failed",
            "finished_at": _now(),
            "error": "Orphaned: server restarted while job was running",
        })


def shutdown() -> None:
    """Cancel all worker tasks and shut down the executor."""
    global _workers, _executor
    for task in _workers:
        task.cancel()
    _workers = []
    if _executor:
        _executor.shutdown(wait=False)
        _executor = None
    logger.info("Job queue shut down")
