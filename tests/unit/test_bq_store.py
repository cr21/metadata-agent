"""Unit tests for BigQuery store — uses a mock BQ client, no live API calls.

All inserts now use DML INSERT (bq.query), not the streaming API (insert_rows_json),
to avoid the streaming buffer restriction on subsequent UPDATE/DELETE statements.
"""

from unittest.mock import MagicMock

from app.storage import bq_store

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(existing_hash: str | None = None) -> MagicMock:
    """Return a mock BQ client. existing_hash simulates a pre-existing asset row."""
    client = MagicMock()

    def _query(sql: str, job_config=None):
        job = MagicMock()
        if "SELECT content_hash" in sql:
            job.result.return_value = (
                [MagicMock(**{"__getitem__": lambda self, k: existing_hash})]
                if existing_hash
                else []
            )
        elif any(
            kw in sql
            for kw in ("SELECT run_id", "SELECT job_id", "SELECT result_id", "SELECT edge_id")
        ):
            job.result.return_value = []
        else:
            job.result.return_value = []
        return job

    client.query.side_effect = _query
    return client


def _asset(asset_id: str = "a1", content_hash: str = "hash_v1") -> dict:
    return {
        "asset_id": asset_id,
        "source": "git",
        "kind": "sql_file",
        "identifier": "sql/query.sql",
        "repo_url": None,
        "branch": "main",
        "commit_sha": "abc",
        "content_hash": content_hash,
        "size_bytes": 100,
        "raw_path": ".cache/a1.sql",
    }


# ---------------------------------------------------------------------------
# upsert_asset
# ---------------------------------------------------------------------------

def test_bq_insert_new_asset():
    """New asset (no existing row) → DML INSERT via bq.query → returns 'inserted'."""
    client = _make_client(existing_hash=None)
    result = bq_store.upsert_asset(_asset(), client=client)
    assert result == "inserted"
    # Must have made at least 2 query calls: one SELECT check + one DML INSERT
    assert client.query.call_count >= 2
    # Streaming API must NOT be used (streaming buffer blocks subsequent UPDATEs)
    client.insert_rows_json.assert_not_called()


def test_bq_noop_on_hash_match():
    """Existing asset with same hash → returns 'skipped', no write calls."""
    client = _make_client(existing_hash="hash_v1")
    result = bq_store.upsert_asset(_asset(content_hash="hash_v1"), client=client)
    assert result == "skipped"
    client.insert_rows_json.assert_not_called()
    # Only the SELECT check should have run
    assert client.query.call_count == 1


def test_bq_update_on_hash_change():
    """Existing asset with different hash → DML UPDATE → returns 'updated'."""
    call_count = 0

    def _query(sql: str, job_config=None):
        nonlocal call_count
        call_count += 1
        job = MagicMock()
        if call_count == 1 and "SELECT content_hash" in sql:
            row = MagicMock()
            row.__getitem__ = lambda self, k: "hash_v1"
            job.result.return_value = [row]
        else:
            job.result.return_value = []
        return job

    client = MagicMock()
    client.query.side_effect = _query
    result = bq_store.upsert_asset(_asset(content_hash="hash_v2"), client=client)
    assert result == "updated"
    client.insert_rows_json.assert_not_called()


# ---------------------------------------------------------------------------
# upsert_crawl_run
# ---------------------------------------------------------------------------

def test_bq_upsert_crawl_run_inserts_new():
    """New crawl_run → DML INSERT via bq.query (not streaming)."""
    client = _make_client()
    run = {
        "run_id": "r1", "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": None, "sources": '["git"]', "stats": "{}",
        "status": "running", "error": None,
    }
    bq_store.upsert_crawl_run(run, client=client)
    assert client.query.call_count >= 2  # SELECT check + DML INSERT
    client.insert_rows_json.assert_not_called()


# ---------------------------------------------------------------------------
# upsert_lineage_job
# ---------------------------------------------------------------------------

def test_bq_upsert_lineage_job_inserts_new():
    """New lineage_job → DML INSERT via bq.query (not streaming)."""
    client = _make_client()
    job = {
        "job_id": "j1", "asset_id": "a1", "status": "queued",
        "schema_kind": "stm", "llm_model": "gpt-4o",
        "started_at": None, "finished_at": None, "error": None, "input_hash": "h1",
    }
    bq_store.upsert_lineage_job(job, client=client)
    assert client.query.call_count >= 2
    client.insert_rows_json.assert_not_called()


# ---------------------------------------------------------------------------
# upsert_lineage_result / upsert_lineage_edge (idempotent inserts)
# ---------------------------------------------------------------------------

def test_bq_upsert_lineage_result_inserts_new():
    """New lineage_result → DML INSERT via bq.query (not streaming)."""
    client = _make_client()
    result = {
        "result_id": "res1", "asset_id": "a1", "job_id": "j1",
        "schema_kind": "stm", "payload": "{}",
    }
    bq_store.upsert_lineage_result(result, client=client)
    assert client.query.call_count >= 2
    client.insert_rows_json.assert_not_called()


def test_bq_upsert_lineage_edge_inserts_new():
    """New lineage_edge → DML INSERT via bq.query (not streaming)."""
    client = _make_client()
    edge = {
        "edge_id": "e1", "source_asset_id": "a1",
        "target_table": "orders", "target_column": "total",
        "source_table": "order_items", "source_column": "amount",
        "transformation_type": "aggregation", "transformation": "SUM",
        "depth": 1,
    }
    bq_store.upsert_lineage_edge(edge, client=client)
    assert client.query.call_count >= 2
    client.insert_rows_json.assert_not_called()
