"""Assets API routes."""

from fastapi import APIRouter, HTTPException

from app.storage import local_cache

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("")
async def list_assets(
    source: str | None = None,
    kind: str | None = None,
) -> list[dict]:
    """List assets from the local SQLite cache with optional filters."""
    filters = {}
    if source:
        filters["source"] = source
    if kind:
        filters["kind"] = kind
    return local_cache.list_assets(filters=filters or None)


@router.get("/{asset_id}")
async def get_asset(asset_id: str) -> dict:
    """Get a single asset by ID."""
    asset = local_cache.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    return asset
