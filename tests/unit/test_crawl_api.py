"""Unit tests for POST /api/crawl endpoint — mocked crawler."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _mock_crawl_result(project_id: str, **kwargs) -> dict:
    return {
        "run_id": "run-123",
        "status": "succeeded",
        "datasets_crawled": ["sales"],
        "stats": {"inserted": 5, "updated": 0, "skipped": 2},
    }


def test_post_crawl_bigquery_returns_run_id():
    with patch("app.api.crawl.bqc.crawl_project", side_effect=_mock_crawl_result):
        resp = client.post(
            "/api/crawl",
            json={"bigquery": {"project_id": "my-project"}},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "run-123"
    assert data["status"] == "succeeded"
    assert data["stats"]["inserted"] == 5


def test_post_crawl_no_source_returns_400():
    resp = client.post("/api/crawl", json={})
    assert resp.status_code == 400


def test_post_crawl_with_dataset_filter():
    with patch("app.api.crawl.bqc.crawl_project", side_effect=_mock_crawl_result) as mock_crawl:
        resp = client.post(
            "/api/crawl",
            json={"bigquery": {"project_id": "my-project", "dataset_filter": ["sales"]}},
        )
    assert resp.status_code == 200
    call_kwargs = mock_crawl.call_args.kwargs
    assert call_kwargs.get("dataset_filter") == ["sales"]


def test_get_crawl_runs():
    with patch("app.api.crawl.local_cache.list_crawl_runs", return_value=[]):
        resp = client.get("/api/crawl/runs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_assets_empty():
    with patch("app.api.assets.local_cache.list_assets", return_value=[]):
        resp = client.get("/api/assets")
    assert resp.status_code == 200
    assert resp.json() == []
