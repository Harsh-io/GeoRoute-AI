# GeoRoute AI — Architecture

**Status:** proposed by Architect Agent, awaiting approval. No application code was modified to produce this document.
**Baseline commit:** `c6ce1a3` ("added geospatial routing pipeline tests") on branch `main`, 1 commit ahead of `origin/main`.
**Evidence date:** repository inspected directly; every claim below is traceable to a file, a command, or a test run recorded in §9.

---

## 0. Read this first — the repository is in a split state

The working tree does **not** match `HEAD`. This is the single most important fact for every developer.

| Fact | Evidence |
|---|---|
| `git ls-files` returns **26 files, all at the OLD root layout** (`georoute/…`, `tests/…`, `pyproject.toml` at repo root) | `git ls-files` |
| The **entire `georoute/` package, root `pyproject.toml` and root `tests/` are DELETED in the working tree, uncommitted** | `git status` shows 18 ` D` entries |
| The real, current code lives in **`backend/` — which is UNTRACKED** | `git status` shows `?? backend/` |
| `backend/` also holds the `.egg-info` of an editable install whose finder maps `georoute` → `backend/georoute` | `.venv/Lib/site-packages/__editable___georoute_ai_1_0_0_finder.py` → `MAPPING = {'georoute': 'D:\\Evolve\\Development\\Geospatial AI Routing\\backend\\georoute'}` |
| The active venv is **Python 3.12.3** at `.venv/` | `.venv/Scripts/python.exe --version` |

**Consequence:** anyone running the pipeline today is executing the *editable install*, i.e. `backend/georoute`. But `git` believes the project is the root layout. A `git checkout`, `git stash`, `git reset`, or a fresh clone would destroy or resurrect the wrong tree. Per `agents/AGENTS.md` rules 8/9/12, **no agent may run any of those commands**. Resolving this split is Task **T0** and requires explicit user authorization.

---

## 1. What the system must become

Generate and compare three candidate infrastructure routes between two points:

1. **Minimum-distance** route.
2. **Minimum-construction-cost** route.
3. **Minimum-environmental-impact** route.

Railway first, extensible to other infrastructure. Each route must be a real graph/search result over prepared geospatial data, with independently recomputable metrics — **not** a hand-drawn polyline.

---

## 2. What actually exists (gap analysis, repository-backed)

### 2.1 Working, tested

| Capability | Module | Evidence |
|---|---|---|
| Config schema + YAML/env loading, bbox validation | `backend/georoute/config.py` | `tests/test_config.py` 4/4 PASS |
| UTM selection + pixel-snapped target grid | `backend/georoute/utils/crs_utils.py` | `tests/test_crs.py` 4/4 PASS |
| Vector ingestion (OSMnx, geometry repair, retry) | `backend/georoute/ingestion/vector_ingestor.py` | `tests/test_regression_fixes.py::TestTenacityRetryIfExceptionType` 3/3 PASS |
| STAC S2 + DEM ingestion, SAS signing | `backend/georoute/ingestion/stac_raster_ingestor.py` | code present; **no unit test** |
| Vector reprojection, optical warp, DEM resample, co-registration audit | `backend/georoute/processing/alignment.py` | `tests/test_alignment.py` 3/3 PASS; DEM/optical closure regression 3/3 PASS |
| COG + GeoJSON export | `backend/georoute/processing/cog_exporter.py` | code present; **no unit test** |
| Pipeline orchestration | `backend/georoute/pipeline.py` | code present; **no end-to-end test** |

**Actual test result (run by Architect):** `26 passed in 4.07s` — `.venv/Scripts/python.exe -m pytest tests/` from `backend/`, and `26 passed` from the repo root.

### 2.2 Present but not doing what its name claims

**The railway router does not route.** `backend/georoute/routing/railway_router.py`:

- `generate_routes()` → `_build_corridor_graph()` downloads an OSMnx graph with **`network_type="drive"`** (roads) at `waypoint_radius_m=2000` around waypoints that are **~30–80 km apart**. Composing those islands yields a **disconnected** graph; `nx.shortest_path` raises `NetworkXNoPath`; the code logs a warning and **silently falls back** to `_synthetic_route_from_waypoints()`.
- Recorded output proves the fallback ran: `data/routes/mandi_delhi/route_metadata.json` has **`"graph_nodes": 0, "graph_edges": 0`**, and the three routes have **12 / 12 / 15 vertices** — exactly the lengths of the three `CORRIDOR_WAYPOINTS` lists.
- The saved geometries are straight polylines through hardcoded coordinates:
  `route_1_shortest` 373.3 km, `route_2_inland` 419.9 km, `route_3_gradient_aware` 375.3 km.
- The three "strategies" are **three hardcoded waypoint lists**, not three objective functions. There is **no construction-cost model and no environmental-impact model anywhere in the router**.
- Only `nx.shortest_path` (Dijkstra) is used. **No A\*, no blocked-edge handling, no explicit unreachable-destination error, no cost surface.**
- The routing tests do not catch any of this: `tests/test_regression_fixes.py::TestRailwayRouting` **constructs `RouteCandidate` objects by hand** and never calls `RailwayRouter`. It asserts "3 routes exist" against fixtures the test itself authored — it cannot fail on the real bug.

### 2.3 Missing entirely

| Missing | Where it should live |
|---|---|
| Segmentation / land-cover / water / obstacle extraction | `backend/georoute/segmentation/` (does not exist) |
| Cost-surface generation (slope, terrain, landcover, water, environmental) | `backend/georoute/cost/` (does not exist) |
| Objective weightings for the three routes | `backend/georoute/objectives/` (does not exist) |
| Route evaluation / comparison metrics | `backend/georoute/evaluation/` (does not exist) |
| FastAPI service | `backend/app/` exists but `main.py`, `api/`, `schemas/`, `services/` are **all empty** (0 bytes / empty dirs) |
| Map visualization | `frontend/` has only empty `package.json`, `vite.config.js`, `src/` |
| Deterministic fixtures | no `tests/fixtures/` anywhere |
| Pinned dependencies | `requirements.txt` uses `>=` ranges only |

### 2.4 Dependency and hygiene defects

- **Undeclared imports:** `networkx` and `pandas` are imported by `railway_router.py` but appear in **neither** `requirements.txt` nor `backend/pyproject.toml`.
- **`fastapi` is not installed** and not declared (verified: `ModuleNotFoundError`). `fiona` is also absent (fine — `pyogrio` 0.13.0 is the active engine).
- **Two competing dependency manifests:** tracked root `requirements.txt` + root `pyproject.toml` vs untracked `backend/pyproject.toml` (near-duplicate). README claims "pinned, tested production dependencies" but nothing is pinned.
- **`.gitignore` is corrupted.** Its first bytes are `@"\r\n.env\r\n…` and it ends with a PowerShell `"@ | Out-File -Encoding utf8 .gitignore` line — a PowerShell heredoc was written literally into the file. It has no rule for `backend/`, which is why the real code is untracked.
- **README is stale:** it documents the old root layout and references `.env.example`, which **does not exist**.
- **The existing audit report is unreliable:** `docs/1.Data Ingestion & Geospatial Preprocessing/part1_audit_report.md` claims "35/35 ✅ production-ready" and links to `georoute/…` paths that are **deleted**, and still lists the DEM closure bug as an open gap when it is fixed. It also never audited routing. Treat it as a claim, not evidence.

### 2.5 Environment note (resolves the Python-version question)

Python **3.11** and **3.14** exist on the host; the geo stack is **not** installable on 3.14 yet. The project already uses **Python 3.12.3** in `.venv/` with a healthy stack — `geopandas 1.1.4, rasterio 1.4.4, shapely 2.1.2, pyproj 3.8.0, osmnx 2.1.1, networkx 3.7, numpy 1.26.4, pystac_client 0.9.0, planetary_computer 1.0.0, pyogrio 0.13.0, pytest 9.1.1`. **Pin `requires-python = ">=3.12,<3.13"`** and keep using `.venv/`.

---

## 3. Target module boundaries

Extend the existing `backend/georoute/` package. **No rewrite.** New capability goes in new subpackages behind explicit contracts; existing signatures are preserved unless a contract requires a documented change.

```
backend/
├── georoute/
│   ├── config.py            [EXISTING — extend schema, do not restructure]
│   ├── pipeline.py          [EXISTING — extend with routing stage]
│   ├── utils/               [EXISTING — crs_utils.py extended, not replaced]
│   ├── io/                  [NEW — reusable vector/raster read/write + validation]   Dev1
│   ├── ingestion/           [EXISTING — extend with rail tags + provenance]          Dev2
│   ├── processing/          [EXISTING — alignment.py extended]                        Dev1
│   ├── segmentation/        [NEW — landcover/water/obstacle layers]                   Dev3
│   ├── cost/                [NEW — cost surfaces + edge-weight functions]             Dev4
│   ├── routing/             [EXISTING — graph build + Dijkstra/A* core]               Dev4
│   ├── objectives/          [NEW — the three objective weightings]                    Dev4
│   ├── evaluation/          [NEW — metrics, comparison table]                         Dev4
│   └── viz/                 [NEW — optional static map export]                        Dev4
├── app/                     [NEW — FastAPI: main.py, api/, schemas/, services/]       T9
└── tests/{unit,integration,live,fixtures}/                                            QA + owners
```

**Ownership rule (from `agents/AGENTS.md` rule 4):** one owner per file. Shared files (`utils/crs_utils.py`, `processing/alignment.py`, `config.py`, `pipeline.py`) are extended **only** by their listed owner and **only** additively (new functions/fields, no signature changes). Any change to a shared file requires a coordination note in `TASK_BOARD.md`.

---

## 4. Data flow (target)

```
 Sources ──────────────► Ingestion ─────► Preprocessing ────► Segmentation ──► Cost ────► Routing ────► Evaluation ─► API ─► Viz
 (STAC S2/DEM, OSM)      Dev2            Dev1                 Dev3              Dev4        Dev4           Dev4           T9     T10
     raw GeoDataFrames    aligned UTM      landcover/water/     cost surfaces    RouteGraph      metrics +      JSON   map
     + signed URLs        vectors + 10m    obstacle layers      (per objective)  + search        comparison
                          rasters          (aligned)                             + 3 routes
```

### Coordinate reference system contract (hard)

- **Single metric CRS for all measurement, costing and routing.** Determined once per AOI by `get_utm_crs_for_bbox()` (`backend/georoute/utils/crs_utils.py`). For the Mandi→Delhi corridor this is **EPSG:32644** (UTM 44N).
- **WGS84 (EPSG:4326) is permitted only at the ingestion boundary and the API/serialization boundary.** No distance, area, slope or cost computation may use degrees.
- Raster grid = `compute_target_raster_grid()`: **10 m** pixels, bounds snapped outward to integer pixel multiples. Every raster in a run shares the same `transform`, `crs`, `width`, `height` — enforced by `SpatialAligner.verify_co_registration()`.
- **Nodata sentinels are fixed and explicit:** DEM `-9999.0`, optical `0.0`. Any cost surface must declare its own `nodata` and must never treat nodata as zero cost.

### Units contract (hard)

| Quantity | Unit |
|---|---|
| Distance / length | metres (`length_m`), km only for display |
| Elevation | metres above ellipsoid/geoid as supplied by `cop-dem-glo-30` |
| Slope | dimensionless rise/run (state if degrees are used at a boundary) |
| Construction cost | **dimensionless "cost units"** with a documented, published weight table; never presented as currency |
| Environmental impact | dimensionless weighted score with documented weights; never presented as a measured impact |
| Raster cost | cost units per pixel; transition cost = per-pixel cost × path length through pixel |

---

## 5. Error-handling rules (hard)

1. **No silent substitution.** If live graph download, STAC, or OSM fails, raise a typed error or return an explicit `status="DEGRADED"` with the reason. The current router's silent synthetic fallback is a defect and must not be reproduced.
2. **Unreachable destination → typed error** (`UnreachableDestinationError`), never a null or a fabricated path.
3. **Prohibited areas are excluded from the graph** (edge removed), never made traversable by a large penalty. Feasibility is separate from preference (`agents/Developer Agent 4.md` rule 8).
4. **CRS mismatch, shape mismatch, transform mismatch → raise.** Never resample implicitly.
5. **Nodata in a cost surface → explicit policy** (`impassable` or `filled`, recorded in the surface's `provenance`), never silently `0`.
6. **Empty layer → preserve schema, log at INFO, continue** (existing `vector_ingestor` behaviour is correct; keep it).
7. **Invalid geometry → `make_valid()` + log count** (existing behaviour; keep it).
8. **Every metric returned must be recomputable** from the returned geometry + input data. `evaluation/` recomputes independently.

---

## 6. Infrastructure decisions

| Question | Decision | Reason |
|---|---|---|
| API framework | **FastAPI** | `backend/app/` is already scaffolded for it; no justified alternative exists. |
| Orchestration (Airflow/Prefect) | **None.** | The pipeline is a single-process, ~70 s run. `backend/georoute/pipeline.py` already orchestrates stages. Adding Airflow **or** Prefect would be unjustified complexity. Revisit only if scheduled multi-AOI batch runs are required. |
| PostgreSQL/PostGIS | **Not now.** | No query pattern requires spatial persistence yet; outputs are GeoJSON + COG files. Introduce only when route/asset persistence or multi-user querying is required — decide at T9. |
| Graph library | **networkx** (already used) | Fine for the graph sizes here; add `scipy.sparse` only if profiling demands it. Declare it as a dependency. |
| Map visualization | Static export first (`viz/`), interactive frontend after API is stable. | Frontend is empty; routing must be correct before it is drawn. |

---

## 7. Integration strategy

- Each developer works in an **isolated branch or git worktree** (`agents/AGENTS.md` rule 5). Suggested: `feat/geo-fixtures`, `feat/cost-routing`, `feat/segmentation`, `test/harness`.
- **Do not commit into `main`.** The integrator (after T0) merges verified work.
- **Do not touch the working-tree deletions of the root layout** — they are another agent's uncommitted state.
- Because the working tree is split, a worktree created from `HEAD` would contain the **old** layout, not `backend/`. Therefore **T0 must complete before parallel worktrees are useful.** Until then, work in place and keep changes additive.
- Every task's rollback is "revert its own branch/commits"; no task may require a destructive git command.

---

## 8. Documentation conventions

This repository already keeps design/audit docs under `docs/` in a numbered-folder style. The four required deliverables therefore live in **`docs/architecture/`**:

- `docs/architecture/ARCHITECTURE.md` (this file)
- `docs/architecture/IMPLEMENTATION_PLAN.md`
- `docs/architecture/MODULE_CONTRACTS.md`
- `docs/architecture/TASK_BOARD.md`

Agent role definitions remain in `agents/`.

---

## 9. Evidence log (commands actually run by the Architect)

```
git status --short                     → 18 deleted tracked files; backend/ agents/ data/ docs/ frontend/ untracked
git ls-files | wc -l                   → 26 (all old root layout)
.venv/Scripts/python.exe --version     → Python 3.12.3
python -c "import <geo stack>"         → geopandas 1.1.4, rasterio 1.4.4, shapely 2.1.2, pyproj 3.8.0,
                                         osmnx 2.1.1, networkx 3.7, numpy 1.26.4, pyogrio 0.13.0,
                                         pystac_client 0.9.0, planetary_computer 1.0.0, pytest 9.1.1
                                         fastapi → ModuleNotFoundError
cd backend && python -m pytest tests/  → 26 passed in 4.07s
python -m pytest (from repo root)      → 26 passed in 3.52s
cat data/routes/mandi_delhi/route_metadata.json → graph_nodes: 0, graph_edges: 0
all_routes_combined.geojson            → route_1_shortest 12 vertices/373.3 km,
                                         route_2_inland 12 vertices/419.9 km,
                                         route_3_gradient_aware 15 vertices/375.3 km
ls backend/app/{api,schemas,services}  → empty; backend/app/main.py → 0 bytes
head -c 120 .gitignore | od -c         → starts with  @"\r\n ; ends with PowerShell Out-File line
ls .env.example                        → No such file or directory
```
