"""Crawl API routes."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.crawlers import bigquery_crawler as bqc
from app.crawlers import git_crawler as gitc
from app.storage import local_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crawl", tags=["crawl"])


class BigQueryCrawlSpec(BaseModel):
    project_id: str
    dataset_filter: list[str] | None = None


class GitCrawlSpec(BaseModel):
    repo_url: str
    branch: str = "main"
    path_prefix: str | None = None


class CrawlRequest(BaseModel):
    bigquery: BigQueryCrawlSpec | None = None
    git: GitCrawlSpec | None = None


class CrawlResponse(BaseModel):
    run_id: str
    status: str
    datasets_crawled: list[str] = []
    stats: dict[str, int]
    repo_url: str | None = None
    branch: str | None = None
    kind_counts: dict[str, int] | None = None
    jobs_enqueued: int = 0


async def _enqueue_changed_assets(changed_asset_ids: list[str]) -> int:
    """Enqueue lineage jobs for each changed/new asset. Returns count enqueued."""
    from app import queue as job_queue
    from app.llm.schemas import KIND_TO_SCHEMA_KIND
    from app.storage import local_cache

    count = 0
    for asset_id in changed_asset_ids:
        asset = local_cache.get_asset(asset_id)
        if asset is None:
            continue
        if asset.get("kind") not in KIND_TO_SCHEMA_KIND:
            logger.debug("Skipping asset %s — kind '%s' has no lineage schema", asset_id, asset.get("kind"))
            continue
        try:
            await job_queue.enqueue_job(asset_id, force=False)
            count += 1
        except Exception:
            logger.exception("Failed to enqueue job for asset %s", asset_id)
    return count


@router.post("", response_model=CrawlResponse)
async def start_crawl(request: CrawlRequest) -> CrawlResponse:
    """
    Kick off a crawl (BigQuery, Git, or both). Returns immediately with run_id.
    Lineage extraction jobs are enqueued in the background for changed assets.
    """
    if request.bigquery is None and request.git is None:
        raise HTTPException(status_code=400, detail="At least one source must be specified.")

    if request.bigquery is not None:
        spec = request.bigquery
        try:
            result = bqc.crawl_project(
                project_id=spec.project_id,
                dataset_filter=spec.dataset_filter,
            )
        except Exception as exc:
            logger.exception("BQ crawl failed for project %s", spec.project_id)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        changed = result.get("changed_asset_ids", [])
        jobs_enqueued = await _enqueue_changed_assets(changed)
        return CrawlResponse(**{k: v for k, v in result.items() if k != "changed_asset_ids"}, jobs_enqueued=jobs_enqueued)

    # Git crawl
    spec_git = request.git
    assert spec_git is not None
    try:
        result = gitc.crawl_repo(
            repo_url=spec_git.repo_url,
            branch=spec_git.branch,
            path_prefix=spec_git.path_prefix,
        )
    except Exception as exc:
        logger.exception("Git crawl failed for %s@%s", spec_git.repo_url, spec_git.branch)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    changed = result.get("changed_asset_ids", [])
    jobs_enqueued = await _enqueue_changed_assets(changed)

    return CrawlResponse(
        run_id=result["run_id"],
        status=result["status"],
        stats=result["stats"],
        repo_url=result["repo_url"],
        branch=result["branch"],
        kind_counts=result["kind_counts"],
        jobs_enqueued=jobs_enqueued,
    )


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
