"""Independent QA Audit script for GeoRoute AI Part 4 Verification."""

import json
from pathlib import Path
import affine
import geopandas as gpd
import numpy as np
import rasterio
import shapely.geometry

def run_audit():
    print("=" * 80)
    print("GEOROUTE AI — PART 4 INDEPENDENT QA AUDIT EXECUTION")
    print("=" * 80)

    # 1. PYORPS Integration Verification
    import pyorps
    print(f"[1] PYORPS Version: {pyorps.__version__}")
    print(f"    PYORPS module file: {pyorps.__file__}")

    # 2. Raster Properties & Coverage Verification
    cost_dir = Path("data/cost/rasters")
    rasters = {
        "distance": cost_dir / "distance_friction.tif",
        "construction": cost_dir / "construction_friction.tif",
        "environmental": cost_dir / "environmental_friction.tif",
        "hard_mask": cost_dir / "hard_constraint_mask.tif",
        "valid_mask": cost_dir / "valid_data_mask.tif",
    }

    for name, p in rasters.items():
        assert p.exists(), f"Raster missing: {p}"
        with rasterio.open(p) as src:
            print(f"[2] Raster '{name}':")
            print(f"    Shape: {src.shape} (height={src.height}, width={src.width})")
            print(f"    CRS: {src.crs}")
            print(f"    Resolution: dx={src.res[0]}, dy={src.res[1]}")
            print(f"    Bounds: Left={src.bounds.left}, Bottom={src.bounds.bottom}, Right={src.bounds.right}, Top={src.bounds.top}")
            print(f"    Width(km): {(src.bounds.right - src.bounds.left)/1000.0:.2f} km, Height(km): {(src.bounds.top - src.bounds.bottom)/1000.0:.2f} km")
            arr = src.read(1)
            valid = arr[arr != src.nodata] if src.nodata is not None else arr
            print(f"    Min: {np.nanmin(valid):.3f}, Max: {np.nanmax(valid):.3f}, Mean: {np.nanmean(valid):.3f}")

    # Inspect distance_friction values
    with rasterio.open(rasters["distance"]) as src:
        d_arr = src.read(1)
        valid_d = d_arr[d_arr > 0]
        print(f"    Distance friction unique values (sample): {np.unique(valid_d)[:5]}")
        print(f"    Is distance friction uniformly 1.0 on valid cells? {bool(np.all(valid_d == 1.0))}")

    # 3. Destination Analysis: Mandi vs New Delhi
    print("\n[3] Endpoints & Geographic Reach Analysis:")
    # New Delhi Railway Station coordinates:
    delhi_lat, delhi_lon = 28.6430, 77.2195
    mandi_lat, mandi_lon = 31.7084, 76.9322
    import pyproj
    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
    mandi_x, mandi_y = transformer.transform(mandi_lon, mandi_lat)
    delhi_x, delhi_y = transformer.transform(delhi_lon, delhi_lat)
    print(f"    Mandi Station UTM 43N: ({mandi_x:.1f}, {mandi_y:.1f})")
    print(f"    New Delhi Station UTM 43N: ({delhi_x:.1f}, {delhi_y:.1f})")

    with rasterio.open(rasters["distance"]) as src:
        b = src.bounds
        mandi_in_bounds = (b.left <= mandi_x <= b.right) and (b.bottom <= mandi_y <= b.top)
        delhi_in_bounds = (b.left <= delhi_x <= b.right) and (b.bottom <= delhi_y <= b.top)
        print(f"    Is Mandi in current raster bounds? {mandi_in_bounds}")
        print(f"    Is New Delhi in current raster bounds? {delhi_in_bounds}")
        crow_dist_km = np.sqrt((delhi_x - mandi_x)**2 + (delhi_y - mandi_y)**2) / 1000.0
        print(f"    Crow-flight distance Mandi to New Delhi: {crow_dist_km:.2f} km")

    # 4. Independent Route Audit from Output Files
    print("\n[4] Inspecting Generated Deliverables:")
    routes_geojson = Path("data/routes/routes.geojson")
    route_results = Path("data/routes/route_results.json")
    routing_manifest = Path("data/routes/routing_manifest.json")

    assert routes_geojson.exists()
    assert route_results.exists()
    assert routing_manifest.exists()

    with open(routing_manifest) as f:
        manifest_data = json.load(f)
    with open(route_results) as f:
        results_data = json.load(f)
    gdf = gpd.read_file(routes_geojson)

    print(f"    Manifest Status: {manifest_data['pipeline_status']}")
    print(f"    Routes in GeoJSON: {len(gdf)}")
    print(f"    Source: {manifest_data['source']['name']} @ {manifest_data['source']['projected_coords']}")
    print(f"    Target: {manifest_data['destination']['name']} @ {manifest_data['destination']['projected_coords']}")

    # Load feature rasters for independent metrics recomputation
    feat_dir = Path("data/features/rasters")
    with rasterio.open(feat_dir / "slope_percent.tif") as s_src:
        slope_pct = s_src.read(1)
        transform = s_src.transform
    with rasterio.open(feat_dir / "classified_landcover.tif") as lc_src:
        landcover = lc_src.read(1)
    with rasterio.open(feat_dir / "water_mask.tif") as w_src:
        water = w_src.read(1)
    with rasterio.open(feat_dir / "building_mask.tif") as b_src:
        building = b_src.read(1)
    with rasterio.open(feat_dir / "highway_mask.tif") as h_src:
        highway = h_src.read(1)

    with rasterio.open(rasters["distance"]) as f_d_src:
        f_dist = f_d_src.read(1)
    with rasterio.open(rasters["construction"]) as f_c_src:
        f_const = f_c_src.read(1)
    with rasterio.open(rasters["environmental"]) as f_e_src:
        f_env = f_e_src.read(1)

    surfaces = {
        "shortest_distance": f_dist,
        "lowest_construction_difficulty": f_const,
        "lowest_environmental_impact": f_env,
    }

    print("\n[5] Independent Verification of Each Route:")
    for idx, r_summary in enumerate(manifest_data["routes"]):
        route_id = r_summary["route_id"]
        obj = r_summary["objective"]
        geom = gdf.loc[gdf["route_id"] == route_id, "geometry"].iloc[0]
        
        # Reproject line coords to UTM 43N to extract cells
        transformer_to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
        pts_utm = [transformer_to_utm.transform(lon, lat) for lon, lat in geom.coords]
        
        # Verify length
        step_dists = []
        for i in range(len(pts_utm) - 1):
            d = np.sqrt((pts_utm[i+1][0] - pts_utm[i][0])**2 + (pts_utm[i+1][1] - pts_utm[i][1])**2)
            step_dists.append(d)
        recomp_geom_len = sum(step_dists)
        
        # Map to cells
        cells = [rasterio.transform.rowcol(transform, x, y) for x, y in pts_utm]
        
        # Check hard constraints on cells
        h_vals = [building[r, c] for r, c in cells]
        b_conflicts = sum(h_vals)
        
        # Sample slope
        slopes = [slope_pct[r, c] for r, c in cells if slope_pct[r, c] >= 0]
        mean_slope = np.mean(slopes)
        max_slope = np.max(slopes)
        
        # Independent cost recomputation
        f_surf = surfaces[obj]
        recomp_cost = 0.0
        for i in range(len(cells) - 1):
            r1, c1 = cells[i]
            r2, c2 = cells[i+1]
            dist_step = step_dists[i]
            avg_f = (float(f_surf[r1, c1]) + float(f_surf[r2, c2])) / 2.0
            recomp_cost += dist_step * avg_f

        print(f"\n--- Route: {route_id} ({obj}) ---")
        print(f"    Reported Length (m): {r_summary['length_m']:.2f} | Recomputed: {recomp_geom_len:.2f} | Diff: {abs(r_summary['length_m'] - recomp_geom_len):.4f} m")
        print(f"    Reported Cost: {r_summary['accumulated_cost']:.2f} | Recomputed: {recomp_cost:.2f} | Diff: {abs(r_summary['accumulated_cost'] - recomp_cost):.4f}")
        print(f"    Units: {r_summary['cost_units']}")
        print(f"    Reported Mean Slope: {r_summary['slope_profile']['mean_percent']:.2f}% | Recomputed: {mean_slope:.2f}%")
        print(f"    Reported Max Slope: {r_summary['slope_profile']['max_percent']:.2f}% | Recomputed: {max_slope:.2f}%")
        print(f"    Building conflicts: {b_conflicts}")
        print(f"    Reported Land Cover: {r_summary['landcover_distribution_percent']}")

    print("\n" + "=" * 80)
    print("AUDIT EXECUTION COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    run_audit()
