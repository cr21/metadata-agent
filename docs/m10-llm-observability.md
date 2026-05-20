# M10 — LLM Observability

## What was built

Every OpenAI API call made by the metadata agent is now captured, stored, and surfaced in a dedicated Streamlit page.

### New components

| Component | Purpose |
|---|---|
| `app/llm/pricing.py` | Model pricing map (5 models) + `compute_usd()` |
| `app/storage/local_cache.py` — `llm_calls` table | Persists each API call with prompts, output, tokens, cost, latency |
| `app/llm/client.py` | Captures `response.usage` and duration; calls `log_llm_call()` per attempt |
| `app/api/llm_calls.py` | `GET /api/llm/calls` and `GET /api/llm/calls/stats` endpoints |
| `ui/streamlit_app.py` — "LLM Calls" page | Summary metrics + filterable table + per-call expander |

### What is captured per call

- `asset_id` and `kind` — which asset triggered the call
- `model` — the OpenAI model used
- `attempt` — 1 for first try, 2 for retry after schema-validation failure
- `system_prompt` and `user_prompt` — full text sent to the API
- `raw_output` — raw JSON string returned by the model
- `prompt_tokens`, `completion_tokens`, `total_tokens` — from `response.usage`
- `usd_cost` — computed via the pricing map
- `duration_ms` — wall-clock latency of the API call
- `created_at` — UTC timestamp

### Pricing coverage

| Model | Input ($/1M) | Output ($/1M) |
|---|---|---|
| gpt-4o | 2.50 | 10.00 |
| gpt-4o-mini | 0.15 | 0.60 |
| gpt-4-turbo | 10.00 | 30.00 |
| gpt-4 | 30.00 | 60.00 |
| gpt-3.5-turbo | 0.50 | 1.50 |

Snapshot-suffix models (e.g. `gpt-4o-2024-08-06`) resolve to their base. Unknown models log a warning and return `0.0`.

## How to verify

1. Start the API: `make api`
2. Start the UI: `make ui`
3. Navigate to the **Crawl** page and run a crawl + lineage extraction.
4. Open the **LLM Calls** page — you should see:
   - Summary metrics (total calls, total tokens, total USD, avg latency)
   - One row per API call in the table
   - Expanding a row reveals the full system prompt, user prompt, and raw JSON output
5. Optionally: `curl localhost:8000/api/llm/calls/stats` and `curl localhost:8000/api/llm/calls`

## Known limitations

- USD cost is 0.0 for models not in the pricing map — a warning is logged.
- Prompts are stored as plain text in SQLite; no encryption at rest.
- Pagination is handled via the `limit` query param (default 100, max 1000) — no cursor-based paging.
