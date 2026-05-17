"""Git repository crawler — clone/pull, walk files, classify, upsert assets."""

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import git

from app.classifier import classify
from app.storage import bq_store, local_cache

logger = logging.getLogger(__name__)

_REPO_CACHE_DIR = Path(".cache") / "repos"


def _repo_slug(repo_url: str) -> str:
    return repo_url.rstrip("/").split("/")[-1].replace(".git", "")


def _local_path(repo_url: str, branch: str) -> Path:
    return _REPO_CACHE_DIR / _repo_slug(repo_url) / branch


def clone_or_pull(repo_url: str, branch: str, local_path: Path) -> git.Repo:
    """Clone if new, pull if already present. Returns git.Repo."""
    if (local_path / ".git").exists():
        repo = git.Repo(local_path)
        origin = repo.remotes.origin
        origin.fetch()
        repo.git.checkout(branch)
        origin.pull()
        logger.info("Pulled %s@%s → %s", repo_url, branch, local_path)
    else:
        local_path.mkdir(parents=True, exist_ok=True)
        repo = git.Repo.clone_from(repo_url, local_path, branch=branch, depth=1)
        logger.info("Cloned %s@%s → %s", repo_url, branch, local_path)
    return repo


def _file_commit_sha(repo: git.Repo, rel_path: str) -> str | None:
    """SHA of the most recent commit that touched rel_path."""
    try:
        commits = list(repo.iter_commits(paths=rel_path, max_count=1))
        return commits[0].hexsha if commits else None
    except Exception:
        return None


def _content_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def crawl_repo(
    repo_url: str,
    branch: str = "main",
    path_prefix: str | None = None,
    store_bq: bool = True,
    _local_repo_path: Path | None = None,
    _db_path: Path | None = None,
) -> dict[str, Any]:
    """Clone/pull repo, classify every text file, upsert assets.

    Args:
        repo_url: Git remote URL to crawl.
        branch: Branch to check out.
        path_prefix: If set, only process files under this relative path.
        store_bq: Write assets to BigQuery canonical store (disable in tests).
        _local_repo_path: Override local clone path (used in tests).
        _db_path: Override SQLite DB path (used in tests).

    Returns:
        dict with run_id, status, stats (inserted/updated/skipped), kind_counts.
    """
    local_path = _local_repo_path or _local_path(repo_url, branch)
    db_kw: dict[str, Any] = {"db_path": _db_path} if _db_path else {}

    run_id = str(uuid.uuid4())
    started_at = datetime.now(UTC).isoformat()

    run_record: dict[str, Any] = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": None,
        "sources": json.dumps({"git": repo_url, "branch": branch}),
        "stats": "{}",
        "status": "running",
        "error": None,
    }
    if store_bq:
        bq_store.upsert_crawl_run(run_record)
    local_cache.upsert_crawl_run(run_record, **db_kw)

    stats: dict[str, int] = {"inserted": 0, "updated": 0, "skipped": 0}
    kind_counts: dict[str, int] = {}
    changed_asset_ids: list[str] = []

    try:
        repo = clone_or_pull(repo_url, branch, local_path)
        now = datetime.now(UTC).isoformat()

        prefix = Path(path_prefix) if path_prefix else None

        for file_path in sorted(local_path.rglob("*")):
            if not file_path.is_file():
                continue

            try:
                rel = file_path.relative_to(local_path)
            except ValueError:
                continue

            rel_str = str(rel)
            if rel_str.startswith(".git"):
                continue
            if prefix and not rel_str.startswith(str(prefix)):
                continue

            try:
                raw = file_path.read_bytes()
            except OSError:
                continue

            try:
                content = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                continue  # skip binary files

            kind = classify(rel_str, content)
            content_hash = _content_hash(raw)
            commit_sha = _file_commit_sha(repo, rel_str)
            asset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{repo_url}#{branch}#{rel_str}"))

            asset: dict[str, Any] = {
                "asset_id": asset_id,
                "source": "git",
                "kind": kind,
                "identifier": rel_str,
                "repo_url": repo_url,
                "branch": branch,
                "commit_sha": commit_sha,
                "content_hash": content_hash,
                "size_bytes": len(raw),
                "raw_path": str(file_path),
                "created_at": now,
                "updated_at": now,
            }

            outcome = local_cache.upsert_asset(asset, **db_kw)
            if store_bq:
                bq_store.upsert_asset(asset)

            stats[outcome] = stats.get(outcome, 0) + 1
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
            if outcome in ("inserted", "updated"):
                changed_asset_ids.append(asset_id)
            logger.debug("git asset %s → %s (%s)", rel_str, outcome, kind)

        finished_at = datetime.now(UTC).isoformat()
        run_record.update(
            {
                "finished_at": finished_at,
                "stats": json.dumps({**stats, "by_kind": kind_counts}),
                "status": "succeeded",
            }
        )
        if store_bq:
            bq_store.upsert_crawl_run(run_record)
        local_cache.upsert_crawl_run(run_record, **db_kw)

        logger.info("Git crawl %s complete: %s kinds=%s", run_id, stats, kind_counts)
        return {
            "run_id": run_id,
            "status": "succeeded",
            "repo_url": repo_url,
            "branch": branch,
            "stats": stats,
            "kind_counts": kind_counts,
            "changed_asset_ids": changed_asset_ids,
        }

    except Exception as exc:
        logger.exception("Git crawl %s failed", run_id)
        finished_at = datetime.now(UTC).isoformat()
        run_record.update(
            {
                "finished_at": finished_at,
                "stats": json.dumps(stats),
                "status": "failed",
                "error": str(exc),
            }
        )
        if store_bq:
            bq_store.upsert_crawl_run(run_record)
        local_cache.upsert_crawl_run(run_record, **db_kw)
        raise
