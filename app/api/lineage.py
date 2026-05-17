"""Lineage API routes."""

import logging

from fastapi import APIRouter, HTTPException

from app.lineage.extractor import extract_lineage
from app.storage import local_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/lineage", tags=["lineage"])


@router.post("/extract/{asset_id}")
async def extract_asset_lineage(asset_id: str) -> dict:
    """Synchronously run lineage extraction for a single asset and store results."""
    asset = local_cache.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}")

    try:
        result = extract_lineage(asset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Lineage extraction failed for asset %s", asset_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "asset_id": asset_id,
        "result_id": result["result_id"],
        "schema_kind": result["schema_kind"],
        "edge_count": result["edge_count"],
    }


@router.post("/refresh/{asset_id}")
async def refresh_asset_lineage(asset_id: str) -> dict:
    """Enqueue a fresh lineage job for an asset, bypassing staleness check."""
    asset = local_cache.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}")

    from app import queue as job_queue
    try:
        job_id = await job_queue.enqueue_job(asset_id, force=True)
    except Exception as exc:
        logger.exception("Failed to enqueue refresh job for asset %s", asset_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"asset_id": asset_id, "job_id": job_id, "status": "queued"}


@router.get("/jobs")
async def list_jobs(status: str | None = None) -> list[dict]:
    """List lineage jobs, optionally filtered by status."""
    jobs = local_cache.list_lineage_jobs()
    if status:
        jobs = [j for j in jobs if j["status"] == status]
    return jobs


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    """Get a single lineage job by ID."""
    job = local_cache.get_lineage_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job


@router.get("/results/{asset_id}")
async def get_lineage_results(asset_id: str) -> list[dict]:
    """List all lineage results for an asset."""
    asset = local_cache.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}")
    return local_cache.list_lineage_results(asset_id)


@router.get("/edges")
async def list_all_edges(depth: int | None = None) -> list[dict]:
    """List all lineage edges, optionally filtered by depth (1 or 2)."""
    return local_cache.list_lineage_edges(depth=depth)


@router.get("/edges/{asset_id}")
async def get_lineage_edges(asset_id: str, depth: int | None = None) -> list[dict]:
    """List lineage edges for an asset, optionally filtered by depth."""
    asset = local_cache.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}")
    return local_cache.list_lineage_edges(source_asset_id=asset_id, depth=depth)
