"""M5 — LLM extractor tests using recorded JSON fixtures (no live API calls)."""

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.lineage.extractor import extract_lineage
from app.llm.client import LLMClient
from app.llm.schemas import DAG_SPEC_SCHEMA, KIND_TO_SCHEMA_KIND, PYSPARK_STM_SCHEMA, STM_SCHEMA
from app.storage import local_cache

FIXTURES = Path(__file__).parent.parent / "fixtures" / "openai"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _make_asset(kind: str, raw_path: str, db_path: Path) -> str:
    asset_id = str(uuid.uuid4())
    local_cache.upsert_asset(
        {
            "asset_id": asset_id,
            "source": "git",
            "kind": kind,
            "identifier": raw_path,
            "repo_url": "https://github.com/cr21/agentic-test-data",
            "branch": "main",
            "commit_sha": "abc1234",
            "content_hash": "deadbeef",
            "size_bytes": 100,
            "raw_path": raw_path,
        },
        db_path=db_path,
    )
    return asset_id


def _mock_client(payload: dict) -> LLMClient:
    client = MagicMock(spec=LLMClient)
    client.extract.return_value = payload
    return client


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_stm_schema_name(self):
        assert STM_SCHEMA["name"] == "stm"
        assert STM_SCHEMA["strict"] is True

    def test_dag_spec_schema_name(self):
        assert DAG_SPEC_SCHEMA["name"] == "dag_spec"
        assert DAG_SPEC_SCHEMA["strict"] is True

    def test_pyspark_stm_schema_name(self):
        assert PYSPARK_STM_SCHEMA["name"] == "pyspark_stm"
        assert PYSPARK_STM_SCHEMA["strict"] is True

    def test_kind_to_schema_kind_mapping(self):
        assert KIND_TO_SCHEMA_KIND["sql_file"] == "stm"
        assert KIND_TO_SCHEMA_KIND["bq_routine"] == "stm"
        assert KIND_TO_SCHEMA_KIND["airflow_dag"] == "dag_spec"
        assert KIND_TO_SCHEMA_KIND["pyspark_file"] == "pyspark_stm"
        assert KIND_TO_SCHEMA_KIND["pandas_file"] == "pyspark_stm"


# ---------------------------------------------------------------------------
# LLMClient validation helper
# ---------------------------------------------------------------------------

class TestLLMClientValidation:
    def test_validate_valid_stm(self):
        payload = _load_fixture("sql_stm.json")
        errors = LLMClient._validate(payload, STM_SCHEMA["schema"])
        assert errors == "", f"Unexpected validation errors: {errors}"

    def test_validate_valid_dag(self):
        payload = _load_fixture("airflow_dag_spec.json")
        errors = LLMClient._validate(payload, DAG_SPEC_SCHEMA["schema"])
        assert errors == "", f"Unexpected validation errors: {errors}"

    def test_validate_valid_pyspark(self):
        payload = _load_fixture("pyspark_stm.json")
        errors = LLMClient._validate(payload, PYSPARK_STM_SCHEMA["schema"])
        assert errors == "", f"Unexpected validation errors: {errors}"

    def test_validate_catches_missing_required_field(self):
        bad = {"stm_entries": [{"target_table": "t"}]}  # missing columns
        errors = LLMClient._validate(bad, STM_SCHEMA["schema"])
        assert errors != ""

    def test_validate_catches_wrong_enum(self):
        bad = {
            "stm_entries": [
                {
                    "target_table": "t",
                    "columns": [
                        {
                            "column": "c",
                            "datatype": "STRING",
                            "source_columns": [],
                            "transformation": "x",
                            "transformation_type": "INVALID_ENUM",
                            "is_pii": False,
                        }
                    ],
                }
            ]
        }
        errors = LLMClient._validate(bad, STM_SCHEMA["schema"])
        assert errors != ""


# ---------------------------------------------------------------------------
# Extractor end-to-end tests (SQL, Airflow, PySpark)
# ---------------------------------------------------------------------------

class TestExtractorSQL:
    def test_sql_fixture_produces_stm_result(self, tmp_path):
        fixture_payload = _load_fixture("sql_stm.json")

        sql_file = tmp_path / "etl_kpi_customer_orders.sql"
        sql_file.write_text("CREATE OR REPLACE PROCEDURE etl_kpi_customer_orders() ...", encoding="utf-8")

        db_path = tmp_path / "index.db"
        asset_id = _make_asset("bq_routine", str(sql_file), db_path)

        result = extract_lineage(asset_id, llm_client=_mock_client(fixture_payload), db_path=db_path)

        assert result["schema_kind"] == "stm"
        assert result["edge_count"] > 0

        results = local_cache.list_lineage_results(asset_id, db_path=db_path)
        assert len(results) == 1
        stored = json.loads(results[0]["payload"])
        assert stored["stm_entries"][0]["target_table"] == "stg_customer_orders"

    def test_sql_edges_stored_correctly(self, tmp_path):
        fixture_payload = _load_fixture("sql_stm.json")
        sql_file = tmp_path / "proc.sql"
        sql_file.write_text("CREATE PROCEDURE ...", encoding="utf-8")
        db_path = tmp_path / "index.db"
        asset_id = _make_asset("sql_file", str(sql_file), db_path)

        extract_lineage(asset_id, llm_client=_mock_client(fixture_payload), db_path=db_path)

        edges = local_cache.list_lineage_edges(source_asset_id=asset_id, db_path=db_path)
        assert len(edges) > 0
        for e in edges:
            assert e["depth"] == 1
            assert e["source_asset_id"] == asset_id
            assert e["target_table"] != ""
            assert e["source_table"] != ""

    def test_sql_idempotent_re_extraction(self, tmp_path):
        """Re-running extraction must not duplicate rows (INSERT OR IGNORE)."""
        fixture_payload = _load_fixture("sql_stm.json")
        sql_file = tmp_path / "proc.sql"
        sql_file.write_text("CREATE PROCEDURE ...", encoding="utf-8")
        db_path = tmp_path / "index.db"
        asset_id = _make_asset("sql_file", str(sql_file), db_path)

        r1 = extract_lineage(asset_id, llm_client=_mock_client(fixture_payload), db_path=db_path)
        # Re-extract with same fixture
        extract_lineage(asset_id, llm_client=_mock_client(fixture_payload), db_path=db_path)

        # lineage_results gets a new row each time (new result_id), but edges are idempotent
        edges_after_second = local_cache.list_lineage_edges(source_asset_id=asset_id, db_path=db_path)
        edges_count = r1["edge_count"]
        # Each edge_id is deterministic — second run should produce no new edges
        assert len(edges_after_second) == edges_count


class TestExtractorAirflow:
    def test_airflow_fixture_produces_dag_spec_result(self, tmp_path):
        fixture_payload = _load_fixture("airflow_dag_spec.json")

        dag_file = tmp_path / "helloworld_dag.py"
        dag_file.write_text("from airflow import DAG\n...", encoding="utf-8")

        db_path = tmp_path / "index.db"
        asset_id = _make_asset("airflow_dag", str(dag_file), db_path)

        result = extract_lineage(asset_id, llm_client=_mock_client(fixture_payload), db_path=db_path)

        assert result["schema_kind"] == "dag_spec"

        results = local_cache.list_lineage_results(asset_id, db_path=db_path)
        assert len(results) == 1
        stored = json.loads(results[0]["payload"])
        assert stored["dag_id"] == "hello_world_week1"
        assert len(stored["tasks"]) == 2


class TestExtractorPySpark:
    def test_pyspark_fixture_produces_pyspark_stm_result(self, tmp_path):
        fixture_payload = _load_fixture("pyspark_stm.json")

        py_file = tmp_path / "process_orders_silver.py"
        py_file.write_text("from pyspark.sql import SparkSession\n...", encoding="utf-8")

        db_path = tmp_path / "index.db"
        asset_id = _make_asset("pyspark_file", str(py_file), db_path)

        result = extract_lineage(asset_id, llm_client=_mock_client(fixture_payload), db_path=db_path)

        assert result["schema_kind"] == "pyspark_stm"
        assert result["edge_count"] > 0

        results = local_cache.list_lineage_results(asset_id, db_path=db_path)
        assert len(results) == 1
        stored = json.loads(results[0]["payload"])
        assert stored["stm_entries"][0]["target_table"] == "silver_db.orders_cleaned"

    def test_pyspark_edges_include_derived_columns(self, tmp_path):
        fixture_payload = _load_fixture("pyspark_stm.json")
        py_file = tmp_path / "spark.py"
        py_file.write_text("from pyspark.sql import SparkSession\n...", encoding="utf-8")
        db_path = tmp_path / "index.db"
        asset_id = _make_asset("pyspark_file", str(py_file), db_path)

        extract_lineage(asset_id, llm_client=_mock_client(fixture_payload), db_path=db_path)

        edges = local_cache.list_lineage_edges(source_asset_id=asset_id, db_path=db_path)
        derived = [e for e in edges if e["target_column"] == "order_val"]
        assert len(derived) == 2  # price and quantity both map to order_val


# ---------------------------------------------------------------------------
# Schema-validation retry path
# ---------------------------------------------------------------------------

class TestSchemaValidationRetry:
    def test_retry_on_bad_first_response(self, tmp_path):
        """Client must retry with tightened prompt when first response fails validation."""
        good_payload = _load_fixture("sql_stm.json")
        bad_payload = {"stm_entries": [{"target_table": "t"}]}  # missing columns

        sql_file = tmp_path / "proc.sql"
        sql_file.write_text("CREATE PROCEDURE ...", encoding="utf-8")
        db_path = tmp_path / "index.db"
        asset_id = _make_asset("sql_file", str(sql_file), db_path)

        call_count = 0

        def fake_call(system, user, schema):
            nonlocal call_count
            call_count += 1
            return bad_payload if call_count == 1 else good_payload

        with patch.object(LLMClient, "_call", side_effect=fake_call):
            real_client = LLMClient.__new__(LLMClient)
            real_client._model = "gpt-4o"

            result = extract_lineage(asset_id, llm_client=real_client, db_path=db_path)

        assert call_count == 2, "Should have called LLM twice (initial + retry)"
        assert result["schema_kind"] == "stm"

    def test_raises_after_two_failures(self, tmp_path):
        """ValueError is raised when both attempts produce invalid output."""
        bad_payload = {"stm_entries": [{"target_table": "t"}]}  # always bad

        sql_file = tmp_path / "proc.sql"
        sql_file.write_text("CREATE PROCEDURE ...", encoding="utf-8")
        db_path = tmp_path / "index.db"
        asset_id = _make_asset("sql_file", str(sql_file), db_path)

        with patch.object(LLMClient, "_call", return_value=bad_payload):
            real_client = LLMClient.__new__(LLMClient)
            real_client._model = "gpt-4o"

            with pytest.raises(ValueError, match="Schema validation failed after retry"):
                extract_lineage(asset_id, llm_client=real_client, db_path=db_path)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestExtractorErrors:
    def test_missing_asset_raises_value_error(self, tmp_path):
        db_path = tmp_path / "index.db"
        with pytest.raises(ValueError, match="Asset not found"):
            extract_lineage("nonexistent-id", llm_client=_mock_client({}), db_path=db_path)

    def test_missing_raw_file_raises_file_not_found(self, tmp_path):
        db_path = tmp_path / "index.db"
        asset_id = _make_asset("sql_file", "/nonexistent/path/file.sql", db_path)
        with pytest.raises(FileNotFoundError):
            extract_lineage(asset_id, llm_client=_mock_client({}), db_path=db_path)

    def test_unknown_kind_raises_value_error(self, tmp_path):
        db_path = tmp_path / "index.db"
        asset_id = _make_asset("unknown", str(tmp_path / "x.txt"), db_path)
        (tmp_path / "x.txt").write_text("hello", encoding="utf-8")
        with pytest.raises(ValueError, match="Cannot extract lineage"):
            extract_lineage(asset_id, llm_client=_mock_client({}), db_path=db_path)
