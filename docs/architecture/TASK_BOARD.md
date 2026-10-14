# GeoRoute AI — Task Board

**Status:** proposed by Architect Agent, awaiting approval. Nothing here is implemented.
**Baseline:** `main` @ `c6ce1a3`. Working tree is split (see `ARCHITECTURE.md` §0) — **T0 blocks all branch/worktree work.**
**Legend:** ☐ not started · ◐ in progress · ☑ done · ⛔ blocked

Every task below names its owner, allowed files, dependencies, inputs, outputs, acceptance criteria,
verification command and rollback. **Update the status and paste the real command output here when you finish.**

---

## Summary

| ID | Task | Owner | Depends | Blocks | Status |
|---|---|---|---|---|---|
| T0 | Resolve working-tree split + commit current layout | @user (integrator) | — | everything | ☐ ⛔ needs authorization |
| T1 | Deps/hygiene fixes, fixtures, baseline freeze | Dev1 + QA | T0 | T2–T10 | ☐ |
| T2 | I/O + validation utilities (`georoute/io/`) | Dev1 | T1 | T4, T8 | ☐ |
| T3 | Extend ingestion (railways/waterways/protected) | Dev2* | T1 | T4 (soft) | ☐ |
| T4 | Slope + cost surfaces (`georoute/cost/`) | Dev4 | T1, T2 | T5 | ☐ |
| T5 | Graph construction + prohibition | Dev4 | T4 | T6 | ☐ |
| T6 | Dijkstra + A* + explicit failure | Dev4 | T5 | T7 | ☐ |
| T7 | Three objectives + evaluation | Dev4 | T6 | T7b, T9 | ☐ |
| T7b | Remove synthetic fallback from existing router | Dev4 | T7 | T9, T10 | ☐ |
| T8 | Segmentation + obstacles (independent) | Dev3* | T2 | — | ☐ |
| T9 | FastAPI service (`backend/app/`) | T9 dev | T7 | T10 | ☐ |
| T10 | Map export + frontend | T10 dev | T7 / T9 | — | ☐ |

\* Dev2 and Dev3 have no seat in the current room. If they are not active, **T3 → Dev1** and **T8 → deferred** (routing is designed not to depend on T8).

---

## T0 — Resolve the working-tree split and commit the current layout

- **Owner:** Architect proposes the change; **execution requires @user authorization** (`agents/AGENTS.md` rules 8/12).
- **Why:** `backend/` holds the real, runnable code but is **untracked**; `git` still tracks the old root layout, whose files are deleted in the working tree. A fresh clone or any `git checkout`/`reset`/`stash` would destroy or resurrect the wrong tree. No developer can safely branch until this is fixed.
- **Allowed files:** git index/working tree only (a commit). **No application source is edited.**
- **Recommended action (A):**
  ```
  git add -A
  git commit -m "Relocate package to backend/; add agents/, docs/, config/, data/ to version control"
  ```
  The 18 deletions and the `backend/` tree are the same content relocated, so history is preserved.
- **Alternative (B):** restore the root layout (`git restore georoute tests pyproject.toml`) and abandon `backend/`. Choose this only if the relocation was accidental.
- **Acceptance:** `git status --short` clean; `git ls-files` includes `backend/georoute/**`; baseline tests still green.
- **Verification:**
  ```
  git status --short
  git ls-files | grep -c "^backend/georoute"
  cd backend && ../.venv/Scripts/python.exe -m pytest tests/ -q
  ```
  Expected: clean status; non-zero file count; `26 passed`.
- **Rollback:** `git revert <sha>` (no history rewrite). If the commit has not been made, nothing changed.

---

## T1 — Dependency + hygiene fixes, fixtures, baseline freeze

- **Owner:** Dev1 (deps + fixtures) with QA (test-layout split).
- **Allowed files:** `backend/pyproject.toml`, `requirements.txt`, `.gitignore`, `backend/georoute/schemas.py` *(new)*, `backend/tests/fixtures/**` *(new)*, `backend/tests/{unit,integration,live}/**` *(new)*, `backend/pytest.ini` *(new)*.
- **Depends:** T0.
- **Inputs:** `ARCHITECTURE.md` §2.4/§2.5, `MODULE_CONTRACTS.md` C0/C6.
- **Outputs:**
  - `networkx`, `pandas`, `pytest` **declared**; `requires-python = ">=3.12,<3.13"`.
  - `.gitignore` repaired: remove the leading `@"` and trailing `"@ | Out-File -Encoding utf8 .gitignore` garbage; keep `data/processed/` ignored; ensure `backend/**/__pycache__/` ignored; **`backend/georoute` must not be ignored**.
  - `schemas.py` with the C0 dataclasses (no behaviour).
  - Fixtures: `tests/fixtures/vector/tiny_layer.geojson` (bowtie + empty + no-CRS), `raster/tiny_dem.tif` (declared nodata, known affine), `graph/tiny_grid.json` (hand-computed optimal, blocked edges, disconnected component, unreachable dest), `terrain/{dem,slope,water}.tif` (hand-computed least-cost path).
  - `pytest.ini` with `markers = live` and `addopts = -m "not live"`.
- **Acceptance:** `pip check` clean; imports resolve from declared deps only; every fixture loads offline; `pytest -m "not live"` green; `git check-ignore backend/georoute/config.py` returns **nothing**.
- **Verification:**
  ```
  cd backend && ../.venv/Scripts/python.exe -m pytest tests/ -q
  cd backend && ../.venv/Scripts/python.exe -c "import networkx, pandas; print('deps ok')"
  git check-ignore -v backend/georoute/config.py   # expect: no output
  ```
- **Rollback:** revert the branch.

---

## T2 — I/O + validation utilities

- **Owner:** Dev1. **Depends:** T1.
- **Allowed files:** `backend/georoute/io/__init__.py`, `backend/georoute/io/readers.py`, `backend/georoute/io/validation.py`, `backend/georoute/utils/crs_utils.py` (**additive: `build_crs_context` only**), `backend/tests/unit/test_io.py`, `backend/tests/unit/test_validation.py`.
- **Inputs:** fixtures `vector/tiny_layer.geojson`, `raster/tiny_dem.tif`.
- **Outputs:** `read_vector`, `read_raster`, `write_vector`, `write_cog`, `validate_geometry`, `assert_aligned`, `reproject`, `build_crs_context` (contract C2).
- **Acceptance:**
  - a layer with no CRS raises `CRSMissingError` (does **not** silently assume EPSG:4326);
  - the bowtie is repaired via `make_valid()` and the repaired/dropped count is reported;
  - empty geometry is handled explicitly;
  - write→read round-trip preserves CRS, transform, nodata and band names;
  - two rasters with different transforms fail `assert_aligned`;
  - `read_raster` raises when nodata is undeclared.
- **Verification:** `cd backend && ../.venv/Scripts/python.exe -m pytest tests/unit/test_io.py tests/unit/test_validation.py -v`
- **Rollback:** new files + one additive function; revert branch.

---

## T3 — Extend ingestion for railway inputs

- **Owner:** Dev2 (→ Dev1 if inactive). **Depends:** T1.
- **Allowed files:** `backend/georoute/ingestion/vector_ingestor.py` (**additive methods only — do not alter `fetch_layer`/`fetch_all`/`_sanitize_geodataframe` signatures**), `config/mandi_delhi_config.yaml`, `backend/tests/integration/test_ingestion_mocked.py`.
- **Outputs:** `fetch_railways`, `fetch_waterways`, `fetch_protected_areas`; provenance (`source`, `acquired_utc`) on every layer.
- **Acceptance:** mocked Overpass responses yield valid EPSG:4326 layers; an empty response yields a schema-preserving empty layer + INFO log; retry behaviour verified with mocks; **no live network call in unit/integration tests**.
- **Verification:** `cd backend && ../.venv/Scripts/python.exe -m pytest tests/integration/test_ingestion_mocked.py -v`
- **Rollback:** revert added methods.

---

## T4 — Slope + cost-surface construction

- **Owner:** Dev4. **Depends:** T1, T2.
- **Allowed files:** `backend/georoute/cost/__init__.py`, `backend/georoute/cost/functions.py`, `backend/georoute/cost/weights.py`, `backend/tests/unit/test_cost.py`.
- **Inputs:** `terrain/{dem,slope,water}.tif`, `CRSContext`.
- **Outputs:** `slope_from_dem`, `proximity_cost`, `distance_cost`, `build_cost_surface`; `CONSTRUCTION_WEIGHTS`, `IMPACT_WEIGHTS` (contract C4).
- **Acceptance:** slope on a synthetic plane matches the analytic value within `1e-6`; nodata policy explicit and recorded in `provenance`; weight tables are published constants with units and are **never** currency or measured impact; cost values on the `terrain/` fixtures match hand-computed numbers.
- **Verification:** `cd backend && ../.venv/Scripts/python.exe -m pytest tests/unit/test_cost.py -v`
- **Rollback:** new files only.

---

## T5 — Graph construction with hard prohibition

- **Owner:** Dev4. **Depends:** T4.
- **Allowed files:** `backend/georoute/routing/graph_builder.py` *(new)*, `backend/tests/unit/test_graph_builder.py`.
- **Outputs:** `build_route_graph(ctx, cost, prohibited, connectivity=8)` → `RouteGraph`.
- **Acceptance:** prohibited features are **absent** from the graph, not merely penalised; the blocked edge set from `graph/tiny_grid.json` is unreachable; graph CRS == run CRS; node coordinates are metres; edge `length_m` matches Euclidean distance on the metric CRS.
- **Verification:** `cd backend && ../.venv/Scripts/python.exe -m pytest tests/unit/test_graph_builder.py -v`
- **Rollback:** new file only.

---

## T6 — Dijkstra + A* with explicit failure

- **Owner:** Dev4. **Depends:** T5.
- **Allowed files:** `backend/georoute/routing/search.py` *(new)*, `backend/tests/unit/test_search.py`.
- **Outputs:** `shortest_path`, `a_star`, `UnreachableDestinationError`.
- **Acceptance:**
  - both algorithms return the **hand-computed** optimal path on `graph/tiny_grid.json`;
  - Dijkstra and A* agree within `rel=1e-6`;
  - equal-cost ties resolve by **lexicographic node id** (documented, reproducible);
  - the disconnected component raises `UnreachableDestinationError` — never `None`, never a fabricated path;
  - the A* heuristic is admissible and its admissibility argument is written down.
- **Verification:** `cd backend && ../.venv/Scripts/python.exe -m pytest tests/unit/test_search.py -v`
- **Rollback:** new file only.

---

## T7 — Three objectives + evaluation

- **Owner:** Dev4. **Depends:** T6.
- **Allowed files:** `backend/georoute/objectives/objectives.py` *(new)*, `backend/georoute/evaluation/metrics.py` *(new)*, `backend/tests/unit/test_objectives.py`, `backend/tests/unit/test_evaluation.py`.
- **Outputs:** `route_min_distance`, `route_min_construction_cost`, `route_min_environmental_impact`, `generate_three_routes`, `recompute_metrics`, `compare_routes`.
- **Acceptance:**
  - the three objectives produce the expected paths on the hand-computed fixture;
  - the three **may legitimately coincide** — if they do, that is documented, not artificially forced apart;
  - every returned metric is recomputed independently from geometry + inputs and matches within tolerance;
  - every metric carries its unit; `status`/`reason` are populated.
- **Verification:** `cd backend && ../.venv/Scripts/python.exe -m pytest tests/unit/test_objectives.py tests/unit/test_evaluation.py -v`
- **Rollback:** new files only.

---

## T7b — Remove the synthetic fallback from the existing router

- **Owner:** Dev4. **Depends:** T7.
- **Allowed files:** `backend/georoute/routing/railway_router.py` (**the only change to an existing routing file**), `backend/tests/unit/test_railway_router_integration.py` *(new)*.
- **Justification (required by `agents/AGENTS.md` rule 6):** today `generate_routes()` silently substitutes hardcoded `CORRIDOR_WAYPOINTS` polylines when the waypoint graph is disconnected. Recorded proof: `route_metadata.json` shows `graph_nodes: 0, graph_edges: 0` and the three routes have 12/12/15 vertices — exactly the waypoint list lengths. The output is a drawing, not a route. `CORRIDOR_WAYPOINTS` must no longer be a routing result.
- **Acceptance:** the three routes come from `generate_three_routes()` over a real `RouteGraph`; failure raises or returns `status="DEGRADED"/"UNREACHABLE"` with a reason; `RouteCandidate`/`RoutingResult` fields preserved; the **new** test calls `RailwayRouter.generate_routes()` for real and asserts `graph_node_count > 0` **or** `status != "OK"`.
- **Verification:** `cd backend && ../.venv/Scripts/python.exe -m pytest tests/unit/test_railway_router_integration.py -v`
- **Rollback:** `git checkout c6ce1a3 -- <old path>` is **not** available (the file moved); revert this file from the T0 commit instead.

---

## T8 — Segmentation + obstacle extraction (independent)

- **Owner:** Dev3 (→ deferred if inactive). **Depends:** T2. **Does not block T4–T7.**
- **Allowed files:** `backend/georoute/segmentation/landcover.py`, `backend/georoute/segmentation/obstacles.py`, `backend/tests/unit/test_segmentation.py`.
- **Outputs:** `segment_landcover`, `to_vector`, `extract_obstacles`; frozen class enum `{0 nodata, 1 water, 2 vegetation, 3 bare, 4 built-up}`.
- **Acceptance:** masks share the input grid; unclassified pixels stay `nodata` and are **never** defaulted to traversable; vectorised features have valid geometry and correct CRS; model id/version/hardware documented; mocked-inference unit test present; **no invented accuracy figures**.
- **Verification:** `cd backend && ../.venv/Scripts/python.exe -m pytest tests/unit/test_segmentation.py -v`
- **Rollback:** new files only. If SAM-Geo is unavailable, report **BLOCKED** and rely on the documented non-segmentation cost surface (contract C3).

---

## T9 — FastAPI service

- **Owner:** T9 dev / integrator. **Depends:** T7.
- **Allowed files:** `backend/app/main.py`, `backend/app/api/routes.py`, `backend/app/schemas/route.py`, `backend/app/services/routing_service.py`, `backend/tests/integration/test_api.py`; add `fastapi`, `uvicorn` to `backend/pyproject.toml`.
- **Outputs:** `POST /api/v1/routes`, `GET /api/v1/routes/{id}`, `GET /healthz` (contract C5).
- **Acceptance:** invalid lat/lon and min≥max rejected with 422; response geometry is GeoJSON EPSG:4326; metrics carry units; `status`/`reason` passed through verbatim; unreachable destination has one documented behaviour and a test for it; OpenAPI schema loads.
- **Verification:**
  ```
  cd backend && ../.venv/Scripts/python.exe -m pytest tests/integration/test_api.py -v
  cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000   # then: curl localhost:8000/healthz
  ```
- **Rollback:** new files only; unmount the router to disable.
- **Open decision:** PostGIS yes/no — default **no** unless a persistence/query requirement appears.

---

## T10 — Map export then frontend

- **Owner:** T10 dev. **Depends:** T7 (static) / T9 (interactive).
- **Allowed files:** `backend/georoute/viz/**` *(new)*, `frontend/**` (currently empty: `package.json`, `vite.config.js`, `src/`).
- **Acceptance:** all three routes render with distinct styling and correct CRS; protected/blocked features overlay correctly; the map shows the same geometries the API returns.
- **Verification:** render the committed fixture AOI; compare displayed geometry to the API GeoJSON.
- **Rollback:** new files only.

---

## Definition of done for a task

Per `agents/AGENTS.md`, every task ends with: **Task status (PASS/FAIL/BLOCKED) · files inspected and changed · tests executed with actual output · evidence · known limitations · exact next step/handoff.**

Paste the real command output into this file. A task whose verification command was not run is **not** done.
