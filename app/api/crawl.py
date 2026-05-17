"""Crawl API routes — implemented in M3/M4."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/crawl", tags=["crawl"])
