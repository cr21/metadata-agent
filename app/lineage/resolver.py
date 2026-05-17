"""Depth-2 transitive lineage resolver."""

import hashlib
import logging
from pathlib import Path

from app.storage import local_cache

logger = logging.getLogger(__name__)


def _edge_id(source_asset_id: str, target_table: str, target_col: str,
             source_table: str, source_col: str, depth: int) -> str:
    key = f"{source_asset_id}|{target_table}|{target_col}|{source_table}|{source_col}|{depth}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def resolve_depth2(db_path: Path = local_cache.DB_PATH) -> int:
    """Compute depth-2 transitive edges from all existing depth-1 edges.

    For each depth-1 edge T ← S, finds depth-1 edges S ← G and writes a
    depth-2 edge T ← G. Skips edges that would form a direct cycle
    (i.e., where G == T for the same table/column). Idempotent.

    Returns the count of depth-2 edges attempted (duplicates are silently
    ignored by the underlying INSERT OR IGNORE).
    """
    depth1 = local_cache.list_lineage_edges(depth=1, db_path=db_path)

    # Build a lookup: (target_table, target_column) → list of depth-1 edges
    # that produce that column, so we can find grandparents in O(1).
    sources_of: dict[tuple[str, str], list[dict]] = {}
    for edge in depth1:
        key = (edge["target_table"], edge["target_column"])
        sources_of.setdefault(key, []).append(edge)

    count = 0
    for edge in depth1:
        target_table = edge["target_table"]
        target_col = edge["target_column"]
        src_table = edge["source_table"]
        src_col = edge["source_column"]

        grandparents = sources_of.get((src_table, src_col), [])
        for gp in grandparents:
            gp_src_table = gp["source_table"]
            gp_src_col = gp["source_column"]

            # Cycle guard: skip if the grandparent source is the original target.
            if gp_src_table == target_table and gp_src_col == target_col:
                logger.debug(
                    "Skipping cycle: %s.%s → %s.%s → %s.%s",
                    target_table, target_col, src_table, src_col,
                    gp_src_table, gp_src_col,
                )
                continue

            depth2_edge = {
                "edge_id": _edge_id(
                    gp["source_asset_id"], target_table, target_col,
                    gp_src_table, gp_src_col, 2,
                ),
                "source_asset_id": gp["source_asset_id"],
                "target_table": target_table,
                "target_column": target_col,
                "source_table": gp_src_table,
                "source_column": gp_src_col,
                "transformation_type": gp.get("transformation_type", "transitive"),
                "transformation": gp.get("transformation", ""),
                "depth": 2,
            }
            local_cache.upsert_lineage_edge(depth2_edge, db_path=db_path)
            count += 1

    logger.debug("resolve_depth2: wrote %d depth-2 edges", count)
    return count
