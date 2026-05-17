"""Unit tests for git crawler — uses tmp_path fixtures; no network calls."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.crawlers import git_crawler as gitc
from app.storage import local_cache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path, files: dict[str, str]) -> tuple[Path, MagicMock]:
    """Write files to tmp_path and return a mock git.Repo."""
    for rel, content in files.items():
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")

    mock_repo = MagicMock()
    mock_repo.iter_commits.return_value = []  # no commit sha in unit tests
    return tmp_path, mock_repo


# ---------------------------------------------------------------------------
# crawl_repo — basic classification and storage
# ---------------------------------------------------------------------------

def test_crawl_repo_classifies_and_inserts_assets(tmp_path):
    files = {
        "queries/report.sql": "SELECT id FROM orders",
        "dags/etl_dag.py": "from airflow import DAG\n",
        "jobs/transform.py": "from pyspark.sql import SparkSession\n",
        "analysis/clean.py": "import pandas as pd\n",
        "sp/calc.sql": "CREATE OR REPLACE PROCEDURE ds.calc() BEGIN SELECT 1; END",
        "README.md": "# test repo",
    }
    local_path, mock_repo = _make_repo(tmp_path, files)
    db_path = tmp_path / "index.db"

    with patch("app.crawlers.git_crawler.clone_or_pull", return_value=mock_repo):
        result = gitc.crawl_repo(
            repo_url="https://github.com/test/repo",
            branch="main",
            store_bq=False,
            _local_repo_path=local_path,
            _db_path=db_path,
        )

    assert result["status"] == "succeeded"
    stats = result["stats"]
    assert stats["inserted"] > 0
    assert stats.get("updated", 0) == 0

    kind_counts = result["kind_counts"]
    assert kind_counts.get("sql_file") == 1
    assert kind_counts.get("airflow_dag") == 1
    assert kind_counts.get("pyspark_file") == 1
    assert kind_counts.get("pandas_file") == 1
    assert kind_counts.get("bq_routine") == 1
    assert kind_counts.get("unknown") == 1  # README.md

    assets = local_cache.list_assets(db_path=db_path)
    assert len(assets) == 6
    sources = {a["source"] for a in assets}
    assert sources == {"git"}


def test_crawl_repo_idempotent(tmp_path):
    """Second crawl with identical content → all skipped."""
    files = {
        "q.sql": "SELECT 1",
        "dag.py": "from airflow import DAG\n",
    }
    local_path, mock_repo = _make_repo(tmp_path, files)
    db_path = tmp_path / "index.db"

    kwargs = dict(
        repo_url="https://github.com/test/repo",
        branch="main",
        store_bq=False,
        _local_repo_path=local_path,
        _db_path=db_path,
    )

    with patch("app.crawlers.git_crawler.clone_or_pull", return_value=mock_repo):
        r1 = gitc.crawl_repo(**kwargs)

    with patch("app.crawlers.git_crawler.clone_or_pull", return_value=mock_repo):
        r2 = gitc.crawl_repo(**kwargs)

    assert r1["stats"]["inserted"] == 2
    assert r2["stats"]["skipped"] == 2
    assert r2["stats"].get("inserted", 0) == 0
    assert r2["stats"].get("updated", 0) == 0


def test_crawl_repo_updates_on_content_change(tmp_path):
    """Changing file content triggers an update on the second crawl."""
    sql_file = tmp_path / "q.sql"
    sql_file.write_text("SELECT 1", encoding="utf-8")

    mock_repo = MagicMock()
    mock_repo.iter_commits.return_value = []
    db_path = tmp_path / "index.db"

    kwargs = dict(
        repo_url="https://github.com/test/repo",
        branch="main",
        store_bq=False,
        _local_repo_path=tmp_path,
        _db_path=db_path,
    )

    with patch("app.crawlers.git_crawler.clone_or_pull", return_value=mock_repo):
        r1 = gitc.crawl_repo(**kwargs)

    sql_file.write_text("SELECT 2", encoding="utf-8")

    with patch("app.crawlers.git_crawler.clone_or_pull", return_value=mock_repo):
        r2 = gitc.crawl_repo(**kwargs)

    assert r1["stats"]["inserted"] == 1
    assert r2["stats"]["updated"] == 1
    assert r2["stats"].get("inserted", 0) == 0


def test_crawl_repo_path_prefix_filter(tmp_path):
    """Only files under path_prefix are processed."""
    files = {
        "dags/etl.py": "from airflow import DAG\n",
        "jobs/transform.py": "from pyspark.sql import SparkSession\n",
        "README.md": "# readme",
    }
    local_path, mock_repo = _make_repo(tmp_path, files)
    db_path = tmp_path / "index.db"

    with patch("app.crawlers.git_crawler.clone_or_pull", return_value=mock_repo):
        gitc.crawl_repo(
            repo_url="https://github.com/test/repo",
            branch="main",
            path_prefix="dags",
            store_bq=False,
            _local_repo_path=local_path,
            _db_path=db_path,
        )

    assets = local_cache.list_assets(db_path=db_path)
    assert len(assets) == 1
    assert assets[0]["kind"] == "airflow_dag"


def test_crawl_repo_skips_binary_files(tmp_path):
    """Binary files (non-UTF-8) are silently skipped."""
    (tmp_path / "data.bin").write_bytes(b"\x00\x01\x02\x03\xff\xfe")
    (tmp_path / "query.sql").write_text("SELECT 1", encoding="utf-8")

    mock_repo = MagicMock()
    mock_repo.iter_commits.return_value = []
    db_path = tmp_path / "index.db"

    with patch("app.crawlers.git_crawler.clone_or_pull", return_value=mock_repo):
        gitc.crawl_repo(
            repo_url="https://github.com/test/repo",
            branch="main",
            store_bq=False,
            _local_repo_path=tmp_path,
            _db_path=db_path,
        )

    assets = local_cache.list_assets(db_path=db_path)
    assert len(assets) == 1
    assert assets[0]["kind"] == "sql_file"


def test_crawl_repo_asset_id_is_deterministic(tmp_path):
    """Same repo/branch/path always produces the same asset_id (uuid5)."""
    (tmp_path / "q.sql").write_text("SELECT 1", encoding="utf-8")

    mock_repo = MagicMock()
    mock_repo.iter_commits.return_value = []
    db_path1 = tmp_path / "db1.db"
    db_path2 = tmp_path / "db2.db"

    with patch("app.crawlers.git_crawler.clone_or_pull", return_value=mock_repo):
        gitc.crawl_repo(
            repo_url="https://github.com/test/repo",
            branch="main",
            store_bq=False,
            _local_repo_path=tmp_path,
            _db_path=db_path1,
        )

    with patch("app.crawlers.git_crawler.clone_or_pull", return_value=mock_repo):
        gitc.crawl_repo(
            repo_url="https://github.com/test/repo",
            branch="main",
            store_bq=False,
            _local_repo_path=tmp_path,
            _db_path=db_path2,
        )

    assets1 = local_cache.list_assets(db_path=db_path1)
    assets2 = local_cache.list_assets(db_path=db_path2)
    assert assets1[0]["asset_id"] == assets2[0]["asset_id"]


def test_crawl_repo_git_dir_is_excluded(tmp_path):
    """Files inside .git/ are never stored as assets."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n  bare = false\n", encoding="utf-8")
    (tmp_path / "real.sql").write_text("SELECT 1", encoding="utf-8")

    mock_repo = MagicMock()
    mock_repo.iter_commits.return_value = []
    db_path = tmp_path / "index.db"

    with patch("app.crawlers.git_crawler.clone_or_pull", return_value=mock_repo):
        gitc.crawl_repo(
            repo_url="https://github.com/test/repo",
            branch="main",
            store_bq=False,
            _local_repo_path=tmp_path,
            _db_path=db_path,
        )

    assets = local_cache.list_assets(db_path=db_path)
    identifiers = [a["identifier"] for a in assets]
    assert not any(".git" in i for i in identifiers)
    assert len(assets) == 1
