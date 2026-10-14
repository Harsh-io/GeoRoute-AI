# GeoRoute AI — Implementation Plan

**Status:** proposed by Architect Agent, awaiting approval. No application code changed.
**Baseline:** `main` @ `c6ce1a3`, working tree split (see `ARCHITECTURE.md` §0).
**Priority order:** T0 (unblock) → T1 (fixtures+baseline) → T2/T3 (preprocessing) → T4–T7 (routing, the actual goal) → T8 (segmentation) → T9/T10 (API, viz).

---

## Guiding constraints

1. **Extend, never rewrite** (`agents/AGENTS.md` §14). Existing tested modules stay; new capability lands in new subpackages.
2. **No destructive git.** No `checkout`/`reset`/`stash`/`clean`/`restore` of the split working tree. T0 needs user authorization.
3. **Honesty over polish.** The router's synthetic fallback must be removed, not hidden. Nothing is "done" until a test exercises the real code path and its result is pasted into `TASK_BOARD.md`.
4. **Routing can proceed without segmentation** (contract C3 decoupling), so the three-objective goal is not blocked on Dev3.

---

## Phase 0 — Unblock and establish truth

### T0 — Resolve the working-tree split and commit the current layout
- **Owner:** Architect proposes; **execution requires @user authorization** (integrator action).
- **Why:** `backend/` (the real code) is untracked; the tracked tree is the deleted old layout. No branch/worktree can be trusted until this is fixed. `agents/AGENTS.md` rule 12 requires approval for a change of this kind.
- **Action (one of, user's choice):**
  - **(A) Recommended:** commit the move as-is — `git add -A` then a single commit "move package to backend/, add agents/ docs/ config/ data/"; the deletions and `backend/` are the same content relocated, so history is preserved and the tree matches reality.
  - **(B)** If the root→backend move is not wanted, restore root layout and abandon `backend/`.
- **Acceptance:** `git status --short` is clean or shows only intentional new work; `git ls-files` includes `backend/georoute/**`; `python -m pytest backend/tests` still returns **26 passed**.
- **Verification:** `git status --short`; `git ls-files | grep backend | wc -l`; `cd backend && ../.venv/Scripts/python.exe -m pytest tests/ -q`
- **Rollback:** the commit is revertible (`git revert <sha>`); no history rewrite.

### T1 — Fix dependency + hygiene defects; add fixtures; freeze the baseline
- **Owner:** Dev1 (fixtures + deps), QA (harness split).
- **Allowed files:** `backend/pyproject.toml`, `requirements.txt`, `backend/georoute/schemas.py` (new), `backend/tests/fixtures/**` (new), `backend/tests/{unit,integration,live}/**` (new), `.gitignore`.
- **Inputs:** `ARCHITECTURE.md` §2.4, contract C6.
- **Outputs:** declared `networkx`, `pandas`, `pytest`; `requires-python = ">=3.12,<3.13"`; a corrected `.gitignore` (remove the PowerShell heredoc garbage, add `backend/**/__pycache__/`, keep `data/processed/` ignored); the four fixture families committed; `pytest.ini`/markers for `live`.
- **Acceptance:** `pip check` clean; `import networkx, pandas` works from declared deps only; fixtures load offline; `pytest -m "not live"` green.
- **Verification:** `../.venv/Scripts/python.exe -m pytest tests/ -m "not live" -q`; `git check-ignore -v backend/georoute/config.py` returns nothing (i.e. tracked).
- **Rollback:** revert branch.

---

## Phase 1 — Geospatial foundation (Dev1)

### T2 — Reusable I/O + validation utilities (`georoute/io/`)
- **Owner:** Dev1. **Depends:** T1.
- **Allowed files:** `backend/georoute/io/readers.py`, `backend/georoute/io/validation.py`, `backend/georoute/schemas.py`, `backend/tests/unit/test_io.py`, `backend/tests/unit/test_validation.py`.
- **Inputs:** fixtures `vector/tiny_layer.geojson`, `raster/tiny_dem.tif`.
- **Outputs:** `read_vector/read_raster/write_vector/write_cog`, `validate_geometry`, `assert_aligned`, `reproject` (contract C2).
- **Acceptance:** CRS-less layer raises `CRSMissingError`; bowtie is repaired and the count reported; empty geometry handled explicitly; read-back of written GeoJSON/COG preserves CRS, transform and nodata; two rasters with differing transforms fail `assert_aligned`.
- **Verification:** `../.venv/Scripts/python.exe -m pytest tests/unit/test_io.py tests/unit/test_validation.py -v`
- **Rollback:** new files only; delete branch.

### T3 — Extend ingestion for railway routing inputs
- **Owner:** Dev2. **Depends:** T1. *(Note: Dev2 has no seat in this room; task is listed for completeness and is reassigned to Dev1 if Dev2 is not active.)*
- **Allowed files:** `backend/georoute/ingestion/vector_ingestor.py` (**additive methods only**), `config/mandi_delhi_config.yaml`, `backend/tests/integration/test_ingestion_mocked.py`.
- **Outputs:** `fetch_railways`, `fetch_waterways`, `fetch_protected_areas`; provenance on every layer.
- **Acceptance:** mocked Overpass responses produce valid EPSG:4326 layers; empty response → schema-preserving empty layer + INFO log; retries verified with mocks; **no live call in the unit/integration suite**.
- **Verification:** `../.venv/Scripts/python.exe -m pytest tests/integration/test_ingestion_mocked.py -v`
- **Rollback:** revert added methods.

---

## Phase 2 — The actual goal: cost surfaces and three real routes (Dev4)

### T4 — Slope + cost-surface construction (`georoute/cost/`)
- **Owner:** Dev4. **Depends:** T1, T2 (for `RasterLayer`), fixtures.
- **Allowed files:** `backend/georoute/cost/functions.py`, `backend/georoute/cost/weights.py`, `backend/tests/unit/test_cost.py`.
- **Outputs:** `slope_from_dem`, `proximity_cost`, `distance_cost`, `build_cost_surface` (contract C4).
- **Acceptance:** slope on a synthetic plane matches the analytic value within `1e-6`; nodata policy is explicit (`impassable`/`filled`) and recorded; `CONSTRUCTION_WEIGHTS` and `IMPACT_WEIGHTS` are published constants with units; a cost surface built from `terrain/` fixtures matches hand-computed values.
- **Verification:** `../.venv/Scripts/python.exe -m pytest tests/unit/test_cost.py -v`
- **Rollback:** new files only.

### T5 — Graph construction with hard prohibition (`georoute/routing/graph_builder.py`)
- **Owner:** Dev4. **Depends:** T4.
- **Outputs:** `build_route_graph(ctx, cost, prohibited, connectivity=8)`; node/edge attrs in metres + cost units.
- **Acceptance:** prohibited features are **absent** from the graph (not merely expensive); a blocked edge set from `graph/tiny_grid.json` is unreachable; graph CRS is the run CRS; node coordinates are metres.
- **Verification:** `../.venv/Scripts/python.exe -m pytest tests/unit/test_graph_builder.py -v`
- **Rollback:** new file only.

### T6 — Dijkstra + A* with explicit failure (`georoute/routing/search.py`)
- **Owner:** Dev4. **Depends:** T5.
- **Outputs:** `shortest_path`, `a_star`, `UnreachableDestinationError`.
- **Acceptance:** both algorithms return the **hand-computed** optimal path on `graph/tiny_grid.json`; Dijkstra and A* agree within `rel=1e-6`; ties resolve by lexicographic node id; the disconnected-component case raises `UnreachableDestinationError` (no null, no fabricated route); A* heuristic is admissible and documented.
- **Verification:** `../.venv/Scripts/python.exe -m pytest tests/unit/test_search.py -v`
- **Rollback:** new file only.

### T7 — Three objectives + evaluation (`georoute/objectives/`, `georoute/evaluation/`)
- **Owner:** Dev4. **Depends:** T6.
- **Outputs:** `route_min_distance`, `route_min_construction_cost`, `route_min_environmental_impact`, `generate_three_routes`; `recompute_metrics`, `compare_routes`.
- **Acceptance:** on the hand-computed fixture the three objectives produce the expected paths and the three may legitimately coincide (documented, not forced apart); every metric is independently recomputed from the geometry + inputs and matches the router's value within tolerance; units are on every metric; `status`/`reason` populated.
- **Verification:** `../.venv/Scripts/python.exe -m pytest tests/unit/test_objectives.py tests/unit/test_evaluation.py -v`
- **Rollback:** new files only.

### T7b — Replace the synthetic fallback in the existing router
- **Owner:** Dev4. **Depends:** T7.
- **Allowed files:** `backend/georoute/routing/railway_router.py` (**the only change to an existing routing file**).
- **Why (per `agents/AGENTS.md` rule 6):** the current `generate_routes()` silently substitutes hardcoded waypoint polylines when the graph is disconnected (`graph_nodes: 0`), which is a false result. `CORRIDOR_WAYPOINTS` must no longer be a routing output; it may remain only as an explicitly-labelled test/visualisation aid, or be removed.
- **Acceptance:** the three routes come from `generate_three_routes()` over a real `RouteGraph`; failure raises or returns `status="DEGRADED"/"UNREACHABLE"` with a reason; a **new test calls `RailwayRouter.generate_routes()` for real** (the current `TestRailwayRouting` tests hand-built fixtures and cannot detect this bug); `RouteCandidate`/`RoutingResult` fields preserved.
- **Verification:** `../.venv/Scripts/python.exe -m pytest tests/unit/test_railway_router_integration.py -v` — must assert `graph_node_count > 0` **or** `status != "OK"`.
- **Rollback:** revert this file to `c6ce1a3` version.

---

## Phase 3 — Segmentation (Dev3), independent

### T8 — Land-cover segmentation + obstacle extraction (`georoute/segmentation/`)
- **Owner:** Dev3. **Depends:** T2 (for `RasterLayer` I/O). **Does not block T4–T7.**
- **Allowed files:** `backend/georoute/segmentation/landcover.py`, `backend/georoute/segmentation/obstacles.py`, `backend/tests/unit/test_segmentation.py`.
- **Outputs:** `segment_landcover`, `to_vector`, `extract_obstacles` (contract C3).
- **Acceptance:** output masks are on the same grid as the input; class codes use the frozen enum; unclassified pixels are `nodata`, never defaulted to traversable; vectorised features have valid geometry and correct CRS; model id/version/hardware documented; a mocked-inference unit test covers the pipeline; **no invented accuracy scores**.
- **Verification:** `../.venv/Scripts/python.exe -m pytest tests/unit/test_segmentation.py -v`
- **Rollback:** new files only. If SAM-Geo is unavailable on this hardware, report **BLOCKED** and fall back to the documented non-segmentation cost surface (contract C3).

---

## Phase 4 — Service and visualisation

### T9 — FastAPI service (`backend/app/`)
- **Owner:** T9 dev / integrator. **Depends:** T7.
- **Allowed files:** `backend/app/main.py`, `backend/app/api/routes.py`, `backend/app/schemas/route.py`, `backend/app/services/routing_service.py`, `backend/tests/integration/test_api.py`; declare `fastapi` + `uvicorn` in `backend/pyproject.toml`.
- **Outputs:** `POST /api/v1/routes`, `GET /api/v1/routes/{id}`, `GET /healthz` (contract C5).
- **Acceptance:** request validation rejects invalid lat/lon and min≥max; response geometry is GeoJSON EPSG:4326; metrics carry units; `status`/`reason` passed through verbatim; unreachable destination → HTTP 200 with `status="UNREACHABLE"` **or** a documented 4xx (pick one and test it); OpenAPI schema loads.
- **Verification:** `../.venv/Scripts/python.exe -m pytest tests/integration/test_api.py -v` and `uvicorn app.main:app` + `curl /healthz`.
- **Rollback:** new files only; feature-flag off by not mounting the router.
- **Decision still open:** whether PostGIS is needed — decide here, default **no**.

### T10 — Static map export (`georoute/viz/`) then interactive frontend
- **Owner:** T10 dev. **Depends:** T7 (static) / T9 (interactive).
- **Outputs:** route GeoJSON → PNG/HTML map; then the empty `frontend/` becomes a real map view.
- **Acceptance:** all three routes render with distinct styling and correct CRS; blocked/protected features overlay correctly; the map shows the same geometries the API returns.
- **Rollback:** new files only.

---

## Verification matrix (what "done" means)

| Layer | Command | Must show |
|---|---|---|
| Unit (no network) | `cd backend && ../.venv/Scripts/python.exe -m pytest tests/unit -q` | all pass |
| Integration (mocked) | `... -m pytest tests/integration -q` | all pass, no live calls |
| Live (opt-in) | `... -m pytest tests/live -m live -q` | run manually, results recorded, may be skipped in CI |
| Baseline regression | `... -m pytest tests/test_alignment.py tests/test_config.py tests/test_crs.py tests/test_regression_fixes.py -q` | **26 passed** — must never drop |
| Real router | new `test_railway_router_integration.py` | `graph_node_count > 0` **or** explicit non-OK status |

---

## Risks and mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Working-tree split causes data loss if anyone runs a git command | **Critical** | T0 first; freeze the rule "no destructive git" until resolved |
| Router still silently returns synthetic routes | **High** | T7b + a test that asserts on `graph_node_count`/`status` |
| Overpass/STAC unavailable during dev | Medium | Fixtures (T1) make unit/integration tests offline; live tests are opt-in |
| SAM-Geo unavailable on this hardware | Medium | T8 is decoupled (contract C3); routing ships with slope+water+protected costs |
| Construction-cost / impact weights look authoritative but are invented | **High** | Weights are published constants with units, labelled "dimensionless estimate"; never currency, never a measured impact (`agents/Developer Agent 4.md`) |
| Two dependency manifests drift | Medium | T1 makes `backend/pyproject.toml` the single source; root files become thin shims or are deleted with T0 |

---

## What this plan deliberately does NOT do

- No Airflow, no Prefect, no Celery — the pipeline is a ~70 s single process.
- No PostgreSQL/PostGIS until a query pattern requires it (decide at T9).
- No rewrite of `config.py`, `crs_utils.py`, `alignment.py`, `vector_ingestor.py`, `cog_exporter.py`, `pipeline.py` — they work and are tested.
- No new orchestration framework, no dependency upgrades beyond declaring what is already imported.
