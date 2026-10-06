# GeoRoute AI: Enterprise Geospatial Routing Pipeline
## Part 1: Data Ingestion & Preprocessing

An enterprise-grade, production-ready geospatial data engineering pipeline designed to ingest, clean, standardize, and co-register multi-modal vector and raster data for infrastructure routing applications.

---

### Key Capabilities

1. **Deterministic Metric CRS Standardization**:
   - Computes the optimal local WGS84 Universal Transverse Mercator (UTM) zone for any given bounding box anywhere on Earth.
   - Automatically projects all vector features and raster grids to the unified metric CRS to allow Euclidean and cost-distance routing in meters.

2. **Vector Ingestion & Topological Sanitization**:
   - Ingests `highway` (roads/tracks/paths for routing), `building` (obstacles to avoid), and `boundary=protected_area` / `leisure=nature_reserve` (environmental zones) via `osmnx` and `geopandas`.
   - Filters null/empty geometries, automatically repairs non-simple/self-intersecting geometries via `make_valid()`, and normalizes unhashable attribute types for valid GeoJSON serialization.
   - Resilient against Overpass API rate-limits and network timeouts via `tenacity` exponential backoff.

3. **STAC Satellite Imagery & Elevation Ingestion**:
   - Ingests high-resolution Sentinel-2 L2A optical imagery (10m) filtered for `< 5%` cloud cover over a temporal range via Microsoft Planetary Computer STAC catalog.
   - Ingests 30m Copernicus Global DEM (`cop-dem-glo-30`) over the exact same bounding box.
   - SAS URL signing and automated retry handling with exponential backoff.

4. **Pixel-Perfect Raster Co-Registration**:
   - Defines a unified 10m target grid snapped to integer metric intervals.
   - Warps Sentinel-2 optical bands (Red, Green, Blue, NIR) directly to the target grid using GDAL VSI curl streaming.
   - Resamples 30m DEM to the exact 10m Sentinel-2 pixel grid using `rasterio.warp.reproject` with bilinear or cubic interpolation.
   - Audits co-registration with strict shape, transform, and CRS assertions.

5. **Cloud-Native Artifact Export**:
   - Exports all vector layers to standardized RFC 7946 GeoJSON files.
   - Exports multi-band optical and single-band elevation layers as Cloud Optimized GeoTIFFs (COG) with tiled layout (256x256), DEFLATE compression, and power-of-two internal pyramid overviews.

---

### Project Structure

```text
georoute-ai/
├── config/
│   └── config.yaml             # Bounding box, dates, STAC, vector tags, and processing settings
├── georoute/
│   ├── __init__.py
│   ├── config.py               # Pydantic models with validation and environment resolution
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── logging_config.py   # Colored, structured logging with file logging support
│   │   └── crs_utils.py        # Automatic UTM EPSG determination & snapped raster grid math
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── vector_ingestor.py  # OSMnx ingestion, geometry repair, and retry handling
│   │   └── stac_raster_ingestor.py # STAC catalog query, cloud filtering, and SAS signing
│   ├── processing/
│   │   ├── __init__.py
│   │   ├── alignment.py        # UTM reprojection, rasterio.warp co-registration & audit
│   │   └── cog_exporter.py     # Cloud Optimized GeoTIFF (COG) and GeoJSON exporter
│   └── pipeline.py             # Master GeoRoutePipeline orchestrator
├── main.py                     # CLI entrypoint with flag overrides
├── requirements.txt            # Pinned, tested production dependencies
├── .env.example                # Environment variable template
└── README.md                   # Documentation
```

---

### Prerequisites & API Keys

#### 1. Microsoft Planetary Computer (Recommended STAC Provider)
- **Status**: Free & open access.
- **Obtaining Key**: Casual queries work without a key, but creating a free account at [https://planetarycomputer.microsoft.com/](https://planetarycomputer.microsoft.com/) grants a subscription key that raises rate limits.
- Add your key to `.env`:
  ```bash
  PC_SDK_SUBSCRIPTION_KEY="your-api-key-here"
  ```

#### 2. Copernicus Data Space Ecosystem (CDSE) / Sentinel Hub (Optional)
- For direct CDSE STAC access:
  - Register at [https://dataspace.copernicus.eu/](https://dataspace.copernicus.eu/)
  - Set `SENTINELHUB_CLIENT_ID` and `SENTINELHUB_CLIENT_SECRET` in `.env`.

#### 3. OpenStreetMap Overpass API
- Public endpoint: `https://overpass-api.de/api` (default).
- In corporate or CI/CD pipelines, configure a private/mirrored Overpass endpoint in `.env`:
  ```bash
  OVERPASS_ENDPOINT="https://overpass.kumi.systems/api"
  ```

---

### Installation

```bash
# Clone the repository and navigate to root
cd "Geospatial AI Routing"

# Create a virtual environment
python -m venv .venv

# Activate environment
# On Linux/macOS:
source .venv/bin/activate
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1

# Install pinned dependencies
pip install -r requirements.txt
```

---

### Configuration (`config/config.yaml`)

Edit `config/config.yaml` to configure your target region, date window, and layers:

```yaml
region:
  name: "rural_test_region_10x10km"
  bbox:
    min_lon: 11.4000
    min_lat: 48.1000
    max_lon: 11.5350
    max_lat: 48.1900

temporal:
  start_date: "2023-06-01"
  end_date: "2023-09-30"

stac:
  api_url: "https://planetarycomputer.microsoft.com/api/stac/v1"
  use_planetary_computer: true
  optical:
    collection: "sentinel-2-l2a"
    max_cloud_cover_percent: 5.0
    bands: ["B04", "B03", "B02", "B08"] # Red, Green, Blue, NIR
  elevation:
    collection: "cop-dem-glo-30"
    asset_name: "data"

vector:
  layers:
    highways:
      tags: { "highway": true }
    buildings:
      tags: { "building": true }
    environmental_zones:
      tags: { "boundary": "protected_area", "leisure": "nature_reserve" }
  timeout_seconds: 60

processing:
  dem_resampling_method: "bilinear"
  target_pixel_size_meters: 10.0

export:
  output_dir: "./data/processed"
  cog:
    block_size: 256
    compression: "deflate"
    overview_levels: [2, 4, 8, 16]
```

---

### Running the Pipeline

#### Via CLI:
```bash
# Run with default config
python main.py

# Run with custom config and verbose output
python main.py --config config/my_region.yaml --verbose

# Run with custom output directory
python main.py --output-dir ./data/custom_run
```

#### Programmatic Python Usage:
```python
from georoute.config import PipelineConfig
from georoute.pipeline import GeoRoutePipeline

# 1. Load configuration
config = PipelineConfig.from_yaml("config/config.yaml")

# 2. Instantiate and execute pipeline
pipeline = GeoRoutePipeline(config)
results = pipeline.execute()

print("Execution Summary:")
print(f"Target Metric CRS: EPSG:{results['utm_epsg']}")
print(f"Grid Dimensions: {results['grid_dimensions']}")
print(f"Optical COG: {results['artifacts']['optical_cog']}")
print(f"DEM COG: {results['artifacts']['dem_cog']}")
```

---

### Output Artifacts

After execution, the following structure is created under `data/processed/`:

```text
data/processed/
├── pipeline.log                     # Comprehensive execution log
├── rasters/
│   ├── optical_sentinel2_10m_*.tif  # 4-band COG (Red, Green, Blue, NIR)
│   └── dem_copernicus_10m_*.tif     # 1-band COG Resampled DEM (meters)
└── vectors/
    ├── highways.geojson             # Reprojected roads with 'length_m'
    ├── buildings.geojson            # Reprojected buildings with 'area_m2'
    └── environmental_zones.geojson  # Reprojected protected zones with 'area_m2'
```
