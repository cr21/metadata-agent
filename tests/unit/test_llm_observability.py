"""Unit tests for M10 — LLM Observability."""

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.llm.pricing import compute_usd
from app.storage import local_cache

# ---------------------------------------------------------------------------
# pricing
# ---------------------------------------------------------------------------

def test_compute_usd_known_model():
    # gpt-4o: $2.50/1M input, $10.00/1M output
    cost = compute_usd("gpt-4o", prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert abs(cost - 12.50) < 0.001


def test_compute_usd_mini():
    cost = compute_usd("gpt-4o-mini", prompt_tokens=500_000, completion_tokens=500_000)
    # (0.15 * 0.5) + (0.60 * 0.5) = 0.075 + 0.30 = 0.375
    assert abs(cost - 0.375) < 0.001


def test_compute_usd_snapshot_suffix():
    # "gpt-4o-2024-08-06" should resolve to gpt-4o pricing
    cost = compute_usd("gpt-4o-2024-08-06", prompt_tokens=1_000_000, completion_tokens=0)
    assert abs(cost - 2.50) < 0.001


def test_compute_usd_unknown_model():
    cost = compute_usd("some-unknown-model", prompt_tokens=100_000, completion_tokens=100_000)
    assert cost == 0.0


def test_compute_usd_zero_tokens():
    assert compute_usd("gpt-4o", 0, 0) == 0.0


# ---------------------------------------------------------------------------
# local_cache.log_llm_call / list_llm_calls / get_llm_call_stats
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


def _make_call(asset_id: str = "asset-1", attempt: int = 1) -> dict:
    return {
        "call_id": str(uuid.uuid4()),
        "asset_id": asset_id,
        "kind": "sql_file",
        "model": "gpt-4o",
        "attempt": attempt,
        "system_prompt": "You are a lineage extractor.",
        "user_prompt": "Extract lineage from this SQL.",
        "raw_output": '{"stm_entries": []}',
        "prompt_tokens": 200,
        "completion_tokens": 50,
        "total_tokens": 250,
        "usd_cost": compute_usd("gpt-4o", 200, 50),
        "duration_ms": 1234,
    }


def test_log_and_list_calls(tmp_db: Path):
    call = _make_call()
    local_cache.log_llm_call(call, db_path=tmp_db)

    rows = local_cache.list_llm_calls(db_path=tmp_db)
    assert len(rows) == 1
    assert rows[0]["call_id"] == call["call_id"]
    assert rows[0]["prompt_tokens"] == 200
    assert rows[0]["attempt"] == 1


def test_log_idempotent(tmp_db: Path):
    call = _make_call()
    local_cache.log_llm_call(call, db_path=tmp_db)
    local_cache.log_llm_call(call, db_path=tmp_db)  # duplicate — should be ignored

    rows = local_cache.list_llm_calls(db_path=tmp_db)
    assert len(rows) == 1


def test_list_calls_filter_by_asset_id(tmp_db: Path):
    local_cache.log_llm_call(_make_call(asset_id="asset-A"), db_path=tmp_db)
    local_cache.log_llm_call(_make_call(asset_id="asset-B"), db_path=tmp_db)

    rows = local_cache.list_llm_calls(asset_id="asset-A", db_path=tmp_db)
    assert len(rows) == 1
    assert rows[0]["asset_id"] == "asset-A"


def test_list_calls_limit(tmp_db: Path):
    for _ in range(5):
        local_cache.log_llm_call(_make_call(), db_path=tmp_db)

    rows = local_cache.list_llm_calls(limit=3, db_path=tmp_db)
    assert len(rows) == 3


def test_get_llm_call_stats(tmp_db: Path):
    local_cache.log_llm_call(_make_call(), db_path=tmp_db)
    local_cache.log_llm_call(_make_call(attempt=2), db_path=tmp_db)

    stats = local_cache.get_llm_call_stats(db_path=tmp_db)
    assert stats["total_calls"] == 2
    assert stats["total_tokens"] == 500
    assert stats["total_usd"] > 0


def test_get_llm_call_stats_empty(tmp_db: Path):
    stats = local_cache.get_llm_call_stats(db_path=tmp_db)
    assert stats["total_calls"] == 0
    assert stats["total_usd"] == 0.0


# ---------------------------------------------------------------------------
# LLMClient — logs call on successful extraction
# ---------------------------------------------------------------------------

def test_llm_client_logs_call(tmp_db: Path):
    """LLMClient.extract() should persist one llm_call row per attempt."""
    from app.llm.client import LLMClient

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 100
    mock_usage.completion_tokens = 30
    mock_usage.total_tokens = 130

    valid_payload = json.dumps({"stm_entries": []})

    mock_choice = MagicMock()
    mock_choice.message.content = valid_payload

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    mock_openai = MagicMock()
    mock_openai.chat.completions.create.return_value = mock_response

    client = LLMClient(client=mock_openai, db_path=tmp_db)
    result = client.extract(
        kind="sql_file",
        path="some/file.sql",
        content="SELECT 1",
        asset_id="asset-xyz",
    )

    assert result == {"stm_entries": []}

    rows = local_cache.list_llm_calls(db_path=tmp_db)
    assert len(rows) == 1
    assert rows[0]["asset_id"] == "asset-xyz"
    assert rows[0]["prompt_tokens"] == 100
    assert rows[0]["completion_tokens"] == 30
    assert rows[0]["attempt"] == 1
    assert rows[0]["usd_cost"] > 0


def test_llm_client_logs_retry(tmp_db: Path):
    """On schema-validation failure, a second call is made and both are logged."""
    from app.llm.client import LLMClient

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 50
    mock_usage.completion_tokens = 20
    mock_usage.total_tokens = 70

    bad_payload = json.dumps({"wrong_key": []})
    good_payload = json.dumps({"stm_entries": []})

    def side_effect(**kwargs):
        resp = MagicMock()
        resp.usage = mock_usage
        # First call returns bad payload; second call returns valid payload
        if side_effect.call_count == 0:
            resp.choices[0].message.content = bad_payload
        else:
            resp.choices[0].message.content = good_payload
        side_effect.call_count += 1
        return resp

    side_effect.call_count = 0

    mock_openai = MagicMock()
    mock_openai.chat.completions.create.side_effect = side_effect

    client = LLMClient(client=mock_openai, db_path=tmp_db)
    client.extract(kind="sql_file", path="f.sql", content="SELECT 1", asset_id="asset-retry")

    rows = local_cache.list_llm_calls(db_path=tmp_db)
    assert len(rows) == 2
    attempts = {r["attempt"] for r in rows}
    assert attempts == {1, 2}
