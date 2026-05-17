# M2 — Storage Layer (BigQuery + SQLite)

## What was built

- **`scripts/init_bq_tables.py`** — idempotently creates the `metadata_store` dataset and 5 BigQuery tables (`assets`, `crawl_runs`, `lineage_jobs`, `lineage_results`, `lineage_edges`). Safe to re-run at any time.
- **`app/storage/local_cache.py`** — SQLite cache at `.cache/index.db` mirroring the three high-read tables (`assets`, `crawl_runs`, `lineage_jobs`). All writes use upsert-by-hash: insert on new, update on hash change, no-op on hash match.
- **`app/storage/bq_store.py`** — BigQuery canonical store with the same upsert semantics for all 5 tables. BQ client is injected so tests can mock it without network calls.

## How to run / verify

**Init BQ tables (requires `BQ_METADATA_PROJECT` in `.env`):**
```bash
python scripts/init_bq_tables.py
```

**Verify SQLite cache:**
```bash
python -c "from app.storage.local_cache import list_assets; print(list_assets())"
```

**Run tests:**
```bash
make test   # 17 passed
make lint   # clean
```

## Known limitations

- BQ `upsert_asset` uses two round-trips (SELECT then INSERT/UPDATE) rather than a MERGE DML statement — suitable for v1 write volumes, revisit if write throughput becomes a bottleneck.
- `lineage_results` rows are immutable (re-runs produce new rows); old rows are not purged in v1.
