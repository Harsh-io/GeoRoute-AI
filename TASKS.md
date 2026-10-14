# GeoRoute AI — Detailed Task Board & Implementation Schedule
**Document Version:** 1.0.0  
**Status:** ACTIVE  
**Lead Engineer:** AI Lead Engineer  

---

## Task Management Rules
1. **Single File Ownership**: Each task specifies exactly which files may be edited. Editing unassigned files is strictly prohibited.
2. **Preserve Working Code**: Existing passing tests in `backend/tests/` (26 tests) must remain 100% green at all times.
3. **Evidence Required**: Every task must end with verified test output before moving to the next.

---

## Sprint 1: Analysis, Cost Surfaces & Routing Core

### [TASK-01] Git Working Tree Baseline & Package Cleanup
* **Assignee**: Lead Engineer
* **Allowed Files**: `backend/pyproject.toml`, Git staging
* **Objective**: Reconcile Git status so that the migration of files into `backend/` is recognized cleanly as moves, and ensure editable package install is persisted without phantom deletions.
* **Dependencies**: None
* **Verification Command**: `git status` & `uv run pytest backend/tests`
* **Acceptance Criteria**: Git status is clean and all 26 existing tests pass.

---

### [TASK-02] Topographic Slope & Gradient Calculator
* **Assignee**: Developer Agent 3 (Vision & Analysis)
* **Allowed Files**:
  * `backend/georoute/analysis/__init__.py`
  * `backend/georoute/analysis/slope_calculator.py`
  * `backend/tests/test_slope.py`
* **Objective**: Implement Horn's 2D gradient algorithm to compute percentage slope ($0\% - 100\%+$) and degree slope ($0^\circ - 90^\circ$) from aligned 10m DEM arrays, handling nodata masks properly.
* **Inputs**: Aligned DEM numpy array (`shape: (1, H, W)`), pixel resolution (10m).
* **Outputs**: Slope array (`shape: (1, H, W)`, dtype `float32`).
* **Dependencies**: TASK-01
* **Verification Command**: `uv run pytest backend/tests/test_slope.py`
* **Acceptance Criteria**:
  * Synthetic plane with known 10% slope yields exactly 10.0% ($\pm 0.05\%$).
  * Nodata cells (`-9999.0`) are preserved with no calculation artifacts.

---

### [TASK-03] Multi-Criteria Cost Surface Generator
* **Assignee**: Developer Agent 3 (Vision & Analysis)
* **Allowed Files**:
  * `backend/georoute/analysis/cost_surface.py`
  * `backend/tests/test_cost_surface.py`
* **Objective**: Combine slope grids, vector obstacle rasters (buildings, protected areas), and land cover to output three distinct 2D cost rasters:
  1. `distance_cost`: Base traversal cost (uniform 1.0).
  2. `construction_cost`: Exponential penalty for slope $> 2\%$, heavy penalty for obstacles ($10^6$).
  3. `environmental_cost`: Infinite penalty for nature reserves ($10^9$), base penalty for green cover.
* **Inputs**: Aligned DEM, vector GeoDataFrames (buildings, protected areas), target Affine transform.
* **Outputs**: Dictionary of 3 cost rasters (`np.ndarray`).
* **Dependencies**: TASK-02
* **Verification Command**: `uv run pytest backend/tests/test_cost_surface.py`
* **Acceptance Criteria**:
  * Buildings and protected areas correctly map to high/infinite cost values.
  * Steep terrain is strictly penalized in construction cost surface.

---

### [TASK-04] Three-Objective Corridor Routing Engine
* **Assignee**: Developer Agent 4 (Routing & Optimization)
* **Allowed Files**:
  * `backend/georoute/routing/railway_router.py`
  * `backend/georoute/routing/evaluator.py`
  * `backend/tests/test_routing.py`
* **Objective**: Connect the cost surfaces to the corridor waypoint routing engine, generating 3 genuine candidate alignments (Shortest, Lowest Construction Cost, Lowest Eco Impact) with comprehensive engineering metrics (Length km, Max slope %, Average slope %, Estimated cost score, Eco impact score).
* **Inputs**: Source/Destination coordinates, corridor waypoints, cost surfaces or live graph.
* **Outputs**: `RoutingResult` dataclass with 3 `RouteCandidate` objects and comparative metrics.
* **Dependencies**: TASK-03
* **Verification Command**: `uv run pytest backend/tests/test_routing.py`
* **Acceptance Criteria**:
  * Route 2 (Construction Cost) achieves lower average slope than Route 1.
  * Route 3 (Eco) avoids protected environmental zones.
  * All geometries are valid GeoJSON LineStrings in `EPSG:4326`.

---

## Sprint 2: Production REST API & Web UI

### [TASK-05] FastAPI Backend Implementation
* **Assignee**: Lead Engineer
* **Allowed Files**:
  * `backend/app/main.py`
  * `backend/app/api/__init__.py`
  * `backend/app/api/routes.py`
  * `backend/app/schemas/__init__.py`
  * `backend/app/schemas/route_schemas.py`
  * `backend/tests/test_api.py`
* **Objective**: Implement FastAPI application exposing endpoints:
  * `GET /api/v1/health`
  * `POST /api/v1/routes/generate`
  * `GET /api/v1/routes/compare`
  * `GET /api/v1/layers/metadata`
* **Dependencies**: TASK-04
* **Verification Command**: `uv run pytest backend/tests/test_api.py`
* **Acceptance Criteria**:
  * Endpoints return HTTP 200 with validated Pydantic schemas.
  * Interactive Swagger docs available at `/docs`.

---

### [TASK-06] Interactive Web Map UI
* **Assignee**: Frontend Engineer
* **Allowed Files**:
  * `frontend/package.json`
  * `frontend/vite.config.js`
  * `frontend/index.html`
  * `frontend/src/*`
* **Objective**: Build a clean, responsive, aesthetic frontend displaying:
  * Interactive Leaflet/MapLibre map.
  * 3 colored route candidates toggleable by user.
  * Side-by-side metric comparison card (distance, slope, cost).
  * Layer toggles for terrain and infrastructure.
* **Dependencies**: TASK-05
* **Verification Command**: `npm run build` in `frontend/` & browser subagent UI test.
* **Acceptance Criteria**: Map loads with zero console errors and displays fetched route candidates dynamically from FastAPI backend.

---

### [TASK-07] End-to-End System Integration & Review
* **Assignee**: QA Engineer & Senior Reviewer
* **Allowed Files**:
  * `backend/tests/test_e2e.py`
  * `REVIEW_REPORT.md`
* **Objective**: Run full pipeline test from ingestion to API and UI, verify clean-slate installation, inspect for regressions or security issues, and sign off on MVP release.
* **Dependencies**: TASK-06
* **Verification Command**: `uv run pytest` (all tests) & manual clean startup check.
* **Acceptance Criteria**: 100% test pass rate, no security warnings, working MVP verified.
