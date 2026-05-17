"""M6 — unit tests for the depth-2 transitive lineage resolver."""

from pathlib import Path

from app.lineage.resolver import resolve_depth2
from app.storage import local_cache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_edge(
    db_path: Path,
    edge_id: str,
    source_asset_id: str,
    target_table: str,
    target_col: str,
    source_table: str,
    source_col: str,
    depth: int = 1,
) -> None:
    local_cache.upsert_lineage_edge(
        {
            "edge_id": edge_id,
            "source_asset_id": source_asset_id,
            "target_table": target_table,
            "target_column": target_col,
            "source_table": source_table,
            "source_column": source_col,
            "transformation_type": "direct",
            "transformation": "",
            "depth": depth,
        },
        db_path=db_path,
    )


def _depth2_edges(db_path: Path) -> list[dict]:
    return local_cache.list_lineage_edges(depth=2, db_path=db_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestResolverSimpleAB:
    """Single hop A→B: no grandparents exist, so no depth-2 edges produced."""

    def test_no_depth2_edges(self, tmp_path):
        db = tmp_path / "test.db"
        _insert_edge(db, "e1", "asset1", "B", "col1", "A", "col1")

        count = resolve_depth2(db_path=db)

        assert count == 0
        assert _depth2_edges(db) == []

    def test_idempotent_second_call(self, tmp_path):
        db = tmp_path / "test.db"
        _insert_edge(db, "e1", "asset1", "B", "col1", "A", "col1")

        resolve_depth2(db_path=db)
        count2 = resolve_depth2(db_path=db)

        assert count2 == 0
        assert _depth2_edges(db) == []


class TestResolverChain:
    """Chain C→A→B: must produce depth-2 row C→B."""

    def test_chain_produces_depth2_edge(self, tmp_path):
        db = tmp_path / "test.db"
        _insert_edge(db, "e1", "asset1", "B", "col1", "A", "col1")   # B ← A (depth 1)
        _insert_edge(db, "e2", "asset2", "A", "col1", "C", "col1")   # A ← C (depth 1)

        count = resolve_depth2(db_path=db)

        assert count == 1
        edges = _depth2_edges(db)
        assert len(edges) == 1
        e = edges[0]
        assert e["target_table"] == "B"
        assert e["target_column"] == "col1"
        assert e["source_table"] == "C"
        assert e["source_column"] == "col1"
        assert e["depth"] == 2

    def test_chain_idempotent(self, tmp_path):
        """Running resolver twice must not duplicate edges."""
        db = tmp_path / "test.db"
        _insert_edge(db, "e1", "asset1", "B", "col1", "A", "col1")
        _insert_edge(db, "e2", "asset2", "A", "col1", "C", "col1")

        resolve_depth2(db_path=db)
        resolve_depth2(db_path=db)

        assert len(_depth2_edges(db)) == 1


class TestResolverDiamond:
    """Diamond: D←B, D←C, B←A, C←A → depth-2 edges must include A as source of D."""

    def test_diamond_resolves_grandparent(self, tmp_path):
        db = tmp_path / "test.db"
        _insert_edge(db, "e1", "asset1", "D", "col1", "B", "col1")  # D ← B
        _insert_edge(db, "e2", "asset1", "D", "col1", "C", "col1")  # D ← C
        _insert_edge(db, "e3", "asset2", "B", "col1", "A", "col1")  # B ← A
        _insert_edge(db, "e4", "asset3", "C", "col1", "A", "col1")  # C ← A

        count = resolve_depth2(db_path=db)

        assert count >= 1
        edges = _depth2_edges(db)
        d_sources = {(e["source_table"], e["source_column"]) for e in edges if e["target_table"] == "D"}
        assert ("A", "col1") in d_sources

    def test_diamond_target_columns_correct(self, tmp_path):
        db = tmp_path / "test.db"
        _insert_edge(db, "e1", "asset1", "D", "col1", "B", "col1")
        _insert_edge(db, "e2", "asset1", "D", "col1", "C", "col1")
        _insert_edge(db, "e3", "asset2", "B", "col1", "A", "col1")
        _insert_edge(db, "e4", "asset3", "C", "col1", "A", "col1")

        resolve_depth2(db_path=db)

        for e in _depth2_edges(db):
            assert e["target_table"] == "D"
            assert e["target_column"] == "col1"
            assert e["depth"] == 2


class TestResolverCycle:
    """Cycle A←B←A: must terminate and produce no self-referential edges."""

    def test_cycle_does_not_loop_forever(self, tmp_path):
        db = tmp_path / "test.db"
        _insert_edge(db, "e1", "asset1", "B", "col1", "A", "col1")  # B ← A
        _insert_edge(db, "e2", "asset2", "A", "col1", "B", "col1")  # A ← B (cycle)

        # Must complete without hanging or raising
        count = resolve_depth2(db_path=db)

        assert count == 0

    def test_cycle_produces_no_self_referential_edges(self, tmp_path):
        db = tmp_path / "test.db"
        _insert_edge(db, "e1", "asset1", "B", "col1", "A", "col1")
        _insert_edge(db, "e2", "asset2", "A", "col1", "B", "col1")

        resolve_depth2(db_path=db)

        for e in _depth2_edges(db):
            assert not (
                e["source_table"] == e["target_table"]
                and e["source_column"] == e["target_column"]
            ), f"Self-referential cycle edge found: {e}"

    def test_longer_chain_with_cycle(self, tmp_path):
        """D←C←B←A with A←D creating a longer cycle — must still terminate."""
        db = tmp_path / "test.db"
        _insert_edge(db, "e1", "asset1", "D", "col1", "C", "col1")  # D ← C
        _insert_edge(db, "e2", "asset2", "C", "col1", "B", "col1")  # C ← B
        _insert_edge(db, "e3", "asset3", "B", "col1", "A", "col1")  # B ← A
        _insert_edge(db, "e4", "asset4", "A", "col1", "D", "col1")  # A ← D (cycle back)

        count = resolve_depth2(db_path=db)

        # Only depth-2 non-cycle edges expected (D←B via C, C←A via B)
        assert count >= 0  # must not raise
        for e in _depth2_edges(db):
            assert not (e["source_table"] == e["target_table"] and e["source_column"] == e["target_column"])
