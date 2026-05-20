"""End-to-end integration test — full pipeline on the fixture repo.

Crawls cr21/agentic-test-data (real network), mocks the LLM client so no
OpenAI calls are made, runs extract_lineage for one asset of each supported
kind, and asserts that lineage_edges are written to the local SQLite cache.

Run with:
    pytest tests/integration/test_end_to_end.py -v
"""

from __future__ import annotations

import pytest

from app.crawlers import git_crawler as gitc
from app.lineage.extractor import extract_lineage
from app.storage import local_cache

FIXTURE_REPO = "https://github.com/cr21/agentic-test-data"
FIXTURE_BRANCH = "main"

# ---------------------------------------------------------------------------
# Mock LLM client — returns schema-valid payloads without calling OpenAI
# ---------------------------------------------------------------------------

_STM_PAYLOAD = {
    "stm_entries": [
        {
            "target_table": "project.dataset.target_table",
            "columns": [
                {
                    "column": "id",
                    "datatype": "STRING",
                    "source_columns": [{"table": "project.dataset.source_table", "column": "raw_id"}],
                    "transformation": "direct copy",
                    "transformation_type": "direct",
                    "is_pii": False,
                },
                {
                    "column": "amount",
                    "datatype": "FLOAT64",
                    "source_columns": [{"table": "project.dataset.source_table", "column": "raw_amount"}],
                    "transformation": "cast to float",
                    "transformation_type": "derived",
                    "is_pii": False,
                },
            ],
        }
    ]
}

_PYSPARK_PAYLOAD = {
    "stm_entries": [
        {
            "target_table": "output_silver",
            "target_location_type": "bigquery",
            "write_mode": "overwrite",
            "columns": [
                {
                    "column": "order_id",
                    "datatype": "STRING",
                    "source_columns": [{"table": "bronze_orders", "column": "id"}],
                    "transformation": "identity",
                    "transformation_type": "direct",
                    "spark_function": "col",
                    "is_pii": False,
                },
                {
                    "column": "total",
                    "datatype": "DOUBLE",
                    "source_columns": [{"table": "bronze_orders", "column": "amount"}],
                    "transformation": "sum aggregation",
                    "transformation_type": "derived",
                    "spark_function": "agg",
                    "is_pii": False,
                },
            ],
        }
    ]
}

_DAG_PAYLOAD = {
    "dag_id": "fixture_dag",
    "description": "Fixture Airflow DAG for testing",
    "tasks": [
        {
            "task_id": "load_raw",
            "operator": "PythonOperator",
            "reads_hint": ["raw.orders"],
            "writes_hint": ["staging.orders"],
            "dependencies": [],
            "description": "Load raw orders into staging",
        },
        {
            "task_id": "transform",
            "operator": "PythonOperator",
            "reads_hint": ["staging.orders"],
            "writes_hint": ["mart.orders"],
            "dependencies": ["load_raw"],
            "description": "Transform staging into mart",
        },
    ],
}


class _MockLLMClient:
    """Returns pre-canned valid payloads for any asset kind."""

    def extract(self, kind: str, path: str, content: str, asset_id: str | None = None) -> dict:  # noqa: ARG002
        if kind in ("airflow_dag",):
            return _DAG_PAYLOAD
        if kind in ("pyspark_file", "pandas_file"):
            return _PYSPARK_PAYLOAD
        return _STM_PAYLOAD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def crawled_db(tmp_path_factory):
    """Crawl the fixture repo once for the whole module; return (db_path, assets)."""
    db = tmp_path_factory.mktemp("e2e") / "index.db"
    result = gitc.crawl_repo(
        repo_url=FIXTURE_REPO,
        branch=FIXTURE_BRANCH,
        store_bq=False,
        _db_path=db,
    )
    assert result["status"] == "succeeded", f"Crawl failed: {result}"
    assert result["stats"]["inserted"] > 0, "No assets crawled"
    return db, local_cache.list_assets(db_path=db)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_of_kind(assets: list[dict], *kinds: str) -> dict | None:
    for kind in kinds:
        for a in assets:
            if a["kind"] == kind:
                return a
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCrawlPhase:
    def test_all_expected_kinds_present(self, crawled_db):
        _, assets = crawled_db
        kinds = {a["kind"] for a in assets}
        for expected in ("sql_file", "airflow_dag", "pyspark_file", "pandas_file", "bq_routine"):
            assert expected in kinds, f"Missing kind '{expected}' in crawled assets"

    def test_assets_have_required_fields(self, crawled_db):
        _, assets = crawled_db
        for a in assets:
            assert a.get("asset_id"), "Missing asset_id"
            assert a.get("content_hash"), "Missing content_hash"
            assert a.get("kind"), "Missing kind"
            assert a.get("identifier"), "Missing identifier"


class TestLineageExtractionSQL:
    def test_sql_asset_produces_depth1_edges(self, crawled_db, tmp_path):
        db_path, assets = crawled_db
        asset = _first_of_kind(assets, "sql_file", "bq_routine")
        assert asset, "No sql_file or bq_routine in fixture repo"

        # Isolated DB for this test: copy the crawled asset into it
        isolated_db = tmp_path / "e2e_sql.db"
        local_cache.upsert_asset(asset, db_path=isolated_db)

        mock = _MockLLMClient()
        result = extract_lineage(asset["asset_id"], llm_client=mock, db_path=isolated_db)

        assert result["schema_kind"] == "stm"
        assert result["edge_count"] > 0, "Expected depth-1 edges from SQL asset"

        edges = local_cache.list_lineage_edges(db_path=isolated_db)
        depth1 = [e for e in edges if e["depth"] == 1]
        assert len(depth1) >= 1

    def test_sql_edges_have_required_fields(self, crawled_db, tmp_path):
        db_path, assets = crawled_db
        asset = _first_of_kind(assets, "sql_file", "bq_routine")
        assert asset

        isolated_db = tmp_path / "e2e_sql_fields.db"
        local_cache.upsert_asset(asset, db_path=isolated_db)

        extract_lineage(asset["asset_id"], llm_client=_MockLLMClient(), db_path=isolated_db)
        edges = local_cache.list_lineage_edges(db_path=isolated_db)

        for edge in edges:
            assert edge.get("target_table"), "Edge missing target_table"
            assert edge.get("target_column"), "Edge missing target_column"
            assert edge.get("source_table"), "Edge missing source_table"
            assert edge.get("source_column"), "Edge missing source_column"
            assert edge.get("depth") in (1, 2)


class TestLineageExtractionPySpark:
    def test_pyspark_asset_produces_depth1_edges(self, crawled_db, tmp_path):
        db_path, assets = crawled_db
        asset = _first_of_kind(assets, "pyspark_file", "pandas_file")
        assert asset, "No pyspark_file or pandas_file in fixture repo"

        isolated_db = tmp_path / "e2e_pyspark.db"
        local_cache.upsert_asset(asset, db_path=isolated_db)

        result = extract_lineage(asset["asset_id"], llm_client=_MockLLMClient(), db_path=isolated_db)

        assert result["schema_kind"] == "pyspark_stm"
        assert result["edge_count"] > 0, "Expected depth-1 edges from PySpark asset"

        edges = local_cache.list_lineage_edges(db_path=isolated_db)
        assert any(e["depth"] == 1 for e in edges)


class TestLineageExtractionDAG:
    def test_dag_asset_produces_depth1_edges(self, crawled_db, tmp_path):
        db_path, assets = crawled_db
        asset = _first_of_kind(assets, "airflow_dag")
        assert asset, "No airflow_dag in fixture repo"

        isolated_db = tmp_path / "e2e_dag.db"
        local_cache.upsert_asset(asset, db_path=isolated_db)

        result = extract_lineage(asset["asset_id"], llm_client=_MockLLMClient(), db_path=isolated_db)

        assert result["schema_kind"] == "dag_spec"
        assert result["edge_count"] > 0, "Expected depth-1 edges from DAG asset"


class TestDepth2Resolution:
    """Verify that depth-2 resolver runs cleanly after multiple assets are processed."""

    def test_full_pipeline_two_assets_no_error(self, crawled_db, tmp_path):
        db_path, assets = crawled_db

        # Pick one SQL and one PySpark asset; extract both into the same DB
        sql_asset = _first_of_kind(assets, "sql_file", "bq_routine")
        spark_asset = _first_of_kind(assets, "pyspark_file", "pandas_file")
        assert sql_asset and spark_asset

        isolated_db = tmp_path / "e2e_depth2.db"
        local_cache.upsert_asset(sql_asset, db_path=isolated_db)
        local_cache.upsert_asset(spark_asset, db_path=isolated_db)

        mock = _MockLLMClient()
        r1 = extract_lineage(sql_asset["asset_id"], llm_client=mock, db_path=isolated_db)
        r2 = extract_lineage(spark_asset["asset_id"], llm_client=mock, db_path=isolated_db)

        assert r1["edge_count"] > 0
        assert r2["edge_count"] > 0

        all_edges = local_cache.list_lineage_edges(db_path=isolated_db)
        # Both assets contributed depth-1 edges
        assert len([e for e in all_edges if e["depth"] == 1]) >= 2

    def test_idempotent_extraction(self, crawled_db, tmp_path):
        """Re-running extract_lineage for the same asset must not duplicate edges."""
        db_path, assets = crawled_db
        asset = _first_of_kind(assets, "sql_file", "bq_routine")
        assert asset

        isolated_db = tmp_path / "e2e_idem.db"
        local_cache.upsert_asset(asset, db_path=isolated_db)
        mock = _MockLLMClient()

        r1 = extract_lineage(asset["asset_id"], llm_client=mock, db_path=isolated_db)
        r2 = extract_lineage(asset["asset_id"], llm_client=mock, db_path=isolated_db)

        edges_after_first = r1["edge_count"]
        edges_after_second = r2["edge_count"]

        all_edges = local_cache.list_lineage_edges(db_path=isolated_db)
        depth1 = [e for e in all_edges if e["depth"] == 1]

        # Second run produces the same edge_count but upserts don't add new rows
        assert edges_after_first == edges_after_second
        assert len(depth1) == edges_after_first
