"""Crawl API routes."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.crawlers import bigquery_crawler as bqc
from app.storage import local_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crawl", tags=["crawl"])


class BigQueryCrawlSpec(BaseModel):
    project_id: str
    dataset_filter: list[str] | None = None


class CrawlRequest(BaseModel):
    bigquery: BigQueryCrawlSpec | None = None


class CrawlResponse(BaseModel):
    run_id: str
    status: str
    datasets_crawled: list[str]
    stats: dict[str, int]


@router.post("", response_model=CrawlResponse)
async def start_crawl(request: CrawlRequest) -> CrawlResponse:
    """
    Kick off a synchronous crawl. Returns once the crawl completes.
    (Async queuing is added in M7.)
    """
    if request.bigquery is None:
        raise HTTPException(status_code=400, detail="At least one source must be specified.")

    spec = request.bigquery
    try:
        result = bqc.crawl_project(
            project_id=spec.project_id,
            dataset_filter=spec.dataset_filter,
        )
    except Exception as exc:
        logger.exception("Crawl failed for project %s", spec.project_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return CrawlResponse(**result)


@router.get("/runs")
async def list_crawl_runs() -> list[dict]:
    """List all crawl runs from the local SQLite cache."""
    return local_cache.list_crawl_runs()


@router.get("/runs/{run_id}")
async def get_crawl_run(run_id: str) -> dict:
    """Get a specific crawl run by ID."""
    run = local_cache.get_crawl_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Crawl run not found.")
    return run
