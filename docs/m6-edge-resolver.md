# M6 — Edge Explosion + Depth-2 Resolver

## What was built

`app/lineage/resolver.py` — `resolve_depth2(db_path)` loads all depth-1 edges from SQLite,
builds a `(target_table, target_column) → edges` lookup, then for each edge T←S finds depth-1
edges S←G (grandparents) and writes depth-2 edges T←G.  Cycle detection skips any grandparent
that equals the original target column.  The function is idempotent (`INSERT OR IGNORE`).

`app/lineage/extractor.py` — now calls `resolve_depth2` after depth-1 edge explosion and
returns `depth2_count` in its result dict.

`app/api/lineage.py` — added `GET /api/lineage/edges?depth=<1|2>` (global, no asset filter)
alongside the existing per-asset endpoint.

## How to verify

### 1. Query `lineage_edges` via the API after extracting a chained fixture

```bash
# Start the API server
make api

# Extract lineage for an asset that has a transitive chain
curl -s -X POST http://localhost:8000/api/lineage/extract/<asset_id>

# Query all edges at depth 1
curl -s "http://localhost:8000/api/lineage/edges?depth=1" | python3 -m json.tool

# Query all depth-2 transitive edges
curl -s "http://localhost:8000/api/lineage/edges?depth=2" | python3 -m json.tool
```

### 2. Run unit tests directly

```bash
pytest tests/unit/test_resolver.py -v
```

Expected: 9 tests, all green, covering:
- `TestResolverSimpleAB` — single hop produces no depth-2 edges
- `TestResolverChain` — C→A→B chain produces one depth-2 edge C→B
- `TestResolverDiamond` — diamond shape resolves A as grandparent of D
- `TestResolverCycle` — A←B←A cycle completes without looping and produces no self-referential edges

## Complexity

The resolver runs in O(E) where E = number of depth-1 edges: one linear scan to build the lookup
dict, one linear scan to resolve grandparents with O(1) lookup per edge.

## Known limitations

- Only goes to depth 2; arbitrary-depth BFS is deferred to a future milestone.
- Depth-2 edges carry the grandparent's `source_asset_id`, not the intermediate asset's — this
  is intentional (shows which asset is the ultimate data source).
- Diamond paths produce one depth-2 edge per path (different `source_asset_id`s), so the same
  logical (target, source) pair may appear more than once at depth 2 when reached via multiple
  intermediate tables.
