# M7 — Async Job Queue

## What was built

- **`app/queue.py`** — in-process asyncio job queue with a bounded semaphore (`llm_concurrency`, default 4). Workers run `extract_lineage` in a thread pool so the async event loop is never blocked by LLM calls.
- **`POST /api/crawl`** now returns immediately. After the crawl finishes it enqueues background lineage jobs for every new or changed asset. Response includes `jobs_enqueued` count.
- **`POST /api/lineage/refresh/{asset_id}`** — on-demand re-run that bypasses the staleness check (always runs).
- **`GET /api/lineage/jobs?status=<filter>`** — lists all lineage jobs; optional `status` query param filters by `queued`, `running`, `succeeded`, `failed`, or `stale`.
- **`GET /api/lineage/jobs/{job_id}`** — single job lookup.
- Staleness logic: if `input_hash == content_hash` and a `succeeded` result already exists, the new job is marked `stale` immediately without calling the LLM.

## Job lifecycle

```
enqueue_job()
     │
     ▼
 status=queued   ──[hash match + succeeded result]──▶ status=stale
     │
     ▼
 status=running  (acquires semaphore slot)
     │
     ├──[success]──▶ status=succeeded
     └──[exception]─▶ status=failed
```

## How to verify

### 1. Start the API
```bash
make api
```

### 2. Trigger a crawl — should return instantly
```bash
curl -s -X POST http://localhost:8000/api/crawl \
  -H "Content-Type: application/json" \
  -d '{"git": {"repo_url": "https://github.com/cr21/agentic-test-data", "branch": "main"}}' | jq .
```
Response includes `"jobs_enqueued": <N>` — the API did not wait for LLM extraction.

### 3. Watch jobs progress
```bash
# All jobs
curl -s http://localhost:8000/api/lineage/jobs | jq '.[] | {job_id, status, asset_id}'

# Filter by status
curl -s "http://localhost:8000/api/lineage/jobs?status=succeeded" | jq 'length'
curl -s "http://localhost:8000/api/lineage/jobs?status=stale"     | jq 'length'
curl -s "http://localhost:8000/api/lineage/jobs?status=failed"    | jq '.[].error'
```

### 4. Force re-run a single asset (bypasses staleness)
```bash
ASSET_ID=$(curl -s http://localhost:8000/api/assets | jq -r '.[0].asset_id')
curl -s -X POST http://localhost:8000/api/lineage/refresh/$ASSET_ID | jq .
```

### 5. Second crawl — jobs should be stale
```bash
# Re-crawl the same repo with no changes
curl -s -X POST http://localhost:8000/api/crawl \
  -H "Content-Type: application/json" \
  -d '{"git": {"repo_url": "https://github.com/cr21/agentic-test-data", "branch": "main"}}' | jq .

# After a moment, check — previous succeeded jobs → stale
curl -s "http://localhost:8000/api/lineage/jobs?status=stale" | jq 'length'
```

## Known limitations

- Queue state is in-memory only; jobs are lost on API restart (job rows in SQLite survive but stay in `queued` status).
- No retry on `failed` jobs — use `POST /api/lineage/refresh/{asset_id}` to requeue.
