"""Integration test — crawl the fixture repo (cr21/agentic-test-data).

Run with:  pytest tests/integration/test_git_crawler_integration.py -v

Requires network access and writes a shallow clone to .cache/repos/.
Re-crawling the same branch must produce zero updates (idempotency check).
"""

import pytest

from app.crawlers import git_crawler as gitc

FIXTURE_REPO = "https://github.com/cr21/agentic-test-data"
FIXTURE_BRANCH = "main"


@pytest.fixture()
def isolated_db(tmp_path):
    """Return path to an isolated SQLite file for each test."""
    return tmp_path / "index.db"


def test_fixture_repo_kind_breakdown(isolated_db):
    """Crawl the fixture repo and verify the expected file-kind breakdown."""
    result = gitc.crawl_repo(
        repo_url=FIXTURE_REPO,
        branch=FIXTURE_BRANCH,
        store_bq=False,
        _db_path=isolated_db,
    )

    assert result["status"] == "succeeded"
    kind_counts = result["kind_counts"]

    # At minimum: we have at least one asset of each crawlable kind
    for kind in ("sql_file", "airflow_dag", "pyspark_file", "pandas_file", "bq_routine"):
        assert kind_counts.get(kind, 0) >= 1, (
            f"Expected at least 1 {kind!r} in fixture repo, got {kind_counts}"
        )

    total = result["stats"]["inserted"]
    assert total > 0, "No assets were crawled from the fixture repo"


def test_fixture_repo_idempotent(isolated_db):
    """Second crawl of the same branch with no changes → zero updates."""
    kwargs = dict(
        repo_url=FIXTURE_REPO,
        branch=FIXTURE_BRANCH,
        store_bq=False,
        _db_path=isolated_db,
    )

    r1 = gitc.crawl_repo(**kwargs)
    assert r1["status"] == "succeeded"
    assert r1["stats"]["inserted"] > 0

    r2 = gitc.crawl_repo(**kwargs)
    assert r2["status"] == "succeeded"
    assert r2["stats"].get("inserted", 0) == 0
    assert r2["stats"].get("updated", 0) == 0
    assert r2["stats"]["skipped"] == r1["stats"]["inserted"]
