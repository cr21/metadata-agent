"""FastAPI router — LLM call observability."""

from fastapi import APIRouter, Query

from app.storage import local_cache

router = APIRouter(prefix="/api/llm", tags=["llm-observability"])


@router.get("/calls")
async def list_calls(
    asset_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict]:
    return local_cache.list_llm_calls(asset_id=asset_id, limit=limit)


@router.get("/calls/stats")
async def get_stats() -> dict:
    return local_cache.get_llm_call_stats()
