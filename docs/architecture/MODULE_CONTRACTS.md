# GeoRoute AI — Module Contracts

**Status:** proposed by Architect Agent, awaiting approval.
**Rule:** these are the only interfaces modules may exchange. If a change is needed, request it from the Architect — do not change a signature unilaterally.

Existing files are **extended, not replaced**. Existing function signatures in
`backend/georoute/{config,utils/crs_utils,processing/alignment,ingestion/*,pipeline}.py`
are frozen unless a contract below explicitly says otherwise.

---

## C0. Shared vocabulary (types every developer imports)

New file: `backend/georoute/schemas.py` — **owner: Architect-approved, implemented by Dev1 (T1).** No behaviour, only dataclasses/TypedDicts.

```python
# All geometry is Shapely 2.x. All CRS are pyproj.CRS. All distances in metres.

class CRSContext:                     # produced by crs_utils (existing behaviour)
    crs: pyproj.CRS                   # the single metric CRS for this run (e.g. EPSG:32644)
    transform: Affine                 # 10 m target grid
    width: int
    height: int
    snapped_bounds: tuple[float,float,float,float]   # (minx,miny,maxx,maxy) in crs

class RasterLayer:                    # one aligned raster on the run grid
    data: np.ndarray                  # (bands, height, width), float32
    transform: Affine
    crs: pyproj.CRS
    nodata: float                     # explicit; never None for a cost input
    band_names: list[str]
    provenance: dict                  # {"source":..., "acquired_utc":..., "nodata_policy":...}

class VectorLayer:                    # one layer, reprojected to crs
    gdf: gpd.GeoDataFrame             # .crs == CRSContext.crs
    name: str
    provenance: dict

class CostSurface:                    # Dev4 builds these from RasterLayer + VectorLayer
    data: np.ndarray                  # (height, width) float32, cost units per pixel
    transform: Affine
    crs: pyproj.CRS
    nodata: float
    nodata_policy: str                # "impassable" | "filled"
    unit: str                         # e.g. "dimensionless_cost_units"
    objective: str                    # "distance" | "construction_cost" | "environmental_impact"
    weights: dict                     # published weight table, see C4
    provenance: dict

class RouteGraph:                     # Dev4 builds; both graph and raster modes
    graph: networkx.Graph | None      # node attrs: x,y (metres, crs). edge attrs: length_m, cost
    raster: CostSurface | None        # for raster-mode least-cost path
    mode: str                         # "graph" | "raster"
    crs: pyproj.CRS
    provenance: dict

class RouteCandidate:                 # EXISTS in routing/railway_router.py — extend metadata only
    route_id: str
    strategy: str                     # "min_distance" | "min_cost" | "min_impact"
    geometry: LineString              # WGS84 (EPSG:4326) for output
    nodes: list
    length_m: float                   # metres, recomputed from geometry
    utm_crs: pyproj.CRS
    metadata: dict                    # must include objective, cost_unit, total_cost, provenance

class RouteResult:
    source: Coordinate
    destination: Coordinate
    routes: list[RouteCandidate]      # 1..3
    status: str                       # "OK" | "DEGRADED" | "UNREACHABLE"
    reason: str | None                # required when status != "OK"
    elapsed_seconds: float
```

`Coordinate` and `RouteCandidate` **already exist** in `backend/georoute/routing/railway_router.py`
and keep their current fields. `RouteCandidate.metadata` is the extension point — add keys, never remove.

---

## C1. Dev2 (Data Acquisition) → Dev1 (Geospatial) — **frozen today, extend additively**

Existing, working, do not change signature:

```python
OSMVectorIngestor.fetch_all(aoi_polygon: Polygon, layer_configs: dict) -> dict[str, gpd.GeoDataFrame]
    # each gdf: EPSG:4326, geometry valid & non-empty, list/dict attrs JSON-stringified

STACRasterIngestor.search_optical_scene(bbox, date_range_str, bands, max_cloud_cover_percent, collection)
    -> OpticalSceneMeta(item_id, datetime, cloud_cover, band_urls: dict[str,str])
STACRasterIngestor.search_dem(bbox, collection, asset_name)
    -> DemMeta(collection, asset_urls: list[str])
```

**New required by this architecture (Task T3, Dev2):**

```python
# Add to backend/georoute/ingestion/vector_ingestor.py (additive)
fetch_railways(aoi_polygon) -> gpd.GeoDataFrame          # tags {"railway": True}
fetch_waterways(aoi_polygon) -> gpd.GeoDataFrame         # tags {"waterway": True}, {"natural":"water"}
fetch_protected_areas(aoi_polygon) -> gpd.GeoDataFrame   # boundary=protected_area, leisure=nature_reserve
```

**Handoff guarantees Dev1 may rely on:** CRS is EPSG:4326; geometries valid & non-empty (or the layer is
empty with preserved schema); every returned object carries `provenance` with source URL/asset id and
acquisition timestamp; a failed/empty fetch is explicit, never fabricated.

**Dev1 must not** re-validate CRS or re-run `make_valid` on data from these calls except as a cheap assertion.

---

## C2. Dev1 (Geospatial) → Dev3, Dev4 — **the central contract**

```python
# backend/georoute/io/readers.py  (NEW, Dev1)
read_vector(path) -> VectorLayer                 # raises CRSMissingError if CRS absent
read_raster(path) -> RasterLayer                 # raises on missing nodata declaration
write_vector(gdf, path) -> Path                  # RFC 7946 GeoJSON, WGS84
write_cog(raster_layer, path, tags=None) -> Path # reuses existing GeoDataExporter

# backend/georoute/io/validation.py (NEW, Dev1)
validate_geometry(gdf) -> ValidationReport        # counts fixed/empty/dropped; never silently drops
assert_aligned(a: RasterLayer, b: RasterLayer) -> None   # CRS + transform + shape, else raise
reproject(gdf, crs) -> gpd.GeoDataFrame

# backend/georoute/utils/crs_utils.py (EXISTING — extend additively)
get_utm_crs_for_bbox(min_lon,min_lat,max_lon,max_lat) -> pyproj.CRS          # unchanged
compute_target_raster_grid(bbox_4326, target_crs, pixel_size_meters) -> (Affine,int,int,tuple)  # unchanged
build_crs_context(config: PipelineConfig) -> CRSContext                       # NEW, thin wrapper

# backend/georoute/processing/alignment.py (EXISTING — extend additively)
SpatialAligner(...)                                                            # unchanged
resample_and_align_dem(...) / resample_and_align_optical(...)                   # unchanged
verify_co_registration(optical, dem, tolerance=1e-6) -> bool                    # unchanged
reproject_to_grid(layer, ctx, resampling="bilinear") -> RasterLayer             # NEW
```

**Grid guarantee for Dev3/Dev4:** every `RasterLayer` returned by Dev1 has the **same** `transform`,
`crs`, `width`, `height` as the run's `CRSContext`. If it does not, Dev1 raises — it never resamples silently.

---

## C3. Dev3 (Segmentation) → Dev4 (Cost) — **isolated, so routing can proceed without it**

```python
# backend/georoute/segmentation/landcover.py (NEW, Dev3)
segment_landcover(optical: RasterLayer, model_cfg: dict) -> RasterLayer
    # output: (1,H,W) uint8 class codes on the SAME grid; nodata where unclassified
    # class codes: 0 nodata, 1 water, 2 vegetation, 3 bare, 4 built-up  (frozen enum)
to_vector(mask: RasterLayer, class_codes: list[int]) -> VectorLayer
    # valid geometries, crs == mask.crs, provenance carries model id + version + confidence policy

# backend/georoute/segmentation/obstacles.py (NEW, Dev3)
extract_obstacles(optical: RasterLayer, buildings: VectorLayer) -> VectorLayer
```

**Hard rule:** a segmentation output is **evidence with stated confidence**, never a definitive constraint.
Class codes must be an explicit enum; unclassified pixels stay `nodata` and must not default to a traversable
class. Dev3 must publish model id/version/hardware and must not invent accuracy numbers.

**Decoupling guarantee:** Dev4's cost functions take landcover as an **optional** input. When absent, the
cost surface uses a documented fallback (e.g. slope + water + protected areas only) and records
`provenance["landcover"] = "unavailable"`. This lets routing (T5–T7) complete and be tested while
segmentation (T8) is still in progress.

---

## C4. Dev4 — Cost, Routing, Objectives, Evaluation (self-contained)

```python
# backend/georoute/cost/functions.py (NEW)
slope_from_dem(dem: RasterLayer, ctx: CRSContext) -> RasterLayer          # rise/run, same grid
proximity_cost(feature: VectorLayer, ctx: CRSContext, max_dist_m: float) -> RasterLayer
distance_cost(ctx: CRSContext) -> CostSurface                             # objective="distance"

build_cost_surface(ctx, dem, landcover=None, water=None, protected=None,
                   weights: dict, objective: str) -> CostSurface          # objective in
                                                                          # {"construction_cost","environmental_impact"}

# backend/georoute/cost/weights.py (NEW)
CONSTRUCTION_WEIGHTS: dict   # slope, water_crossing, built_up, earthwork, … (published, dimensionless)
IMPACT_WEIGHTS: dict         # protected_area, vegetation, water_body, habitat_fragmentation, …
# Both tables are documented constants. Never currency. Never a measured impact.

# backend/georoute/routing/graph_builder.py (NEW)
build_route_graph(ctx, cost: CostSurface, prohibited: VectorLayer|None,
                  connectivity: int = 8) -> RouteGraph
    # prohibited features are REMOVED from the graph (not merely penalised)
    # node/edge attrs in metres + cost units on the run CRS

# backend/georoute/routing/search.py (NEW)
shortest_path(graph: RouteGraph, source_xy, dest_xy, weight: str = "cost",
              algorithm: str = "dijkstra") -> list           # raises UnreachableDestinationError
a_star(graph: RouteGraph, source_xy, dest_xy, heuristic) -> list  # heuristic MUST be admissible
    # documented tie-break: lexicographic node id  (Dev4 fixture requirement)

# backend/georoute/objectives/objectives.py (NEW)
route_min_distance(graph: RouteGraph, src, dst) -> RouteCandidate
route_min_construction_cost(graph: RouteGraph, src, dst) -> RouteCandidate
route_min_environmental_impact(graph: RouteGraph, src, dst) -> RouteCandidate
generate_three_routes(graph: RouteGraph, src, dst) -> RouteResult

# backend/georoute/evaluation/metrics.py (NEW)
recompute_metrics(candidate: RouteCandidate, inputs: dict) -> dict
    # {"length_m":…, "total_cost":…, "max_slope":…, "water_crossings":…, "protected_area_m2":…}
compare_routes(result: RouteResult) -> dict   # comparison table for API/UI
```

**Unit + tolerance contract (Dev4 fixture requirement):**
- every cost has a declared unit string; `distance` → metres, others → dimensionless cost units;
- route length is recomputed from the returned geometry with `pyproj.Geod` (metres);
- cost comparison tolerance: **`rel=1e-6`** for Dijkstra vs A* (documented float-accumulation difference);
- ties broken by **lexicographic node id** so "known optimal" is reproducible;
- prohibited edges/cells are unreachable — a test must prove a blocked edge is never traversed;
- unreachable destination raises `UnreachableDestinationError` (explicit status, never a fabricated route).

**RouteCandidate.geometry is WGS84 for output.** Node coordinates inside the graph are metres in the run CRS.
Conversion happens once, at candidate construction.

---

## C5. Dev4 → T9 (API) / T10 (Viz)

```python
# backend/app/services/routing_service.py (NEW, T9)
run_routing(request: RouteRequest) -> RouteResult
# backend/app/schemas/route.py (NEW, T9) — pydantic models mirroring C0
RouteRequest  { source: {lat,lon}, destination: {lat,lon}, objective_set: [...], mode: "graph"|"raster" }
RouteResponse { status, reason|None, routes: [...], comparison: {...} }   # GeoJSON geometry out
# endpoints
POST /api/v1/routes        -> RouteResponse
GET  /api/v1/routes/{id}   -> RouteResponse | 404
GET  /healthz              -> {"status":"ok"}
```

FastAPI is required (not yet installed — T9 installs it and declares it). Geometry is serialized as
**GeoJSON in EPSG:4326**; metrics carry their unit strings. The API must surface `status` and `reason`
verbatim so an unreachable or degraded run is never rendered as a success.

---

## C6. Fixture contract (QA owns the harness, Dev1/Dev4 own their fixtures)

Committed under `backend/tests/fixtures/`:

| Fixture | Owner | Content |
|---|---|---|
| `vector/tiny_layer.geojson` | Dev1 | one self-intersecting bowtie, one empty geometry, one layer with **no CRS metadata** |
| `raster/tiny_dem.tif` | Dev1 | COG-compatible GeoTIFF, declared nodata, known affine transform |
| `graph/tiny_grid.json` | Dev4 | single-digit node graph, hand-computed optimal costs, one blocked edge set, one disconnected component, one unreachable destination |
| `terrain/{dem,slope,water}.tif` | Dev4 | triple with a **hand-computed** least-cost path for raster mode |

Rules: values are written down by hand, **not** produced by the solver. Fixtures are committed to git
(they are small, deterministic and required for offline tests). Tests are split into
`tests/unit/` (no network), `tests/integration/` (mocked), `tests/live/` (real STAC/OSM, opt-in, marked
`@pytest.mark.live` and skipped by default).
