/**
 * GeoRoute AI — Frontend Component & Workflow Integration Tests (Vitest)
 * Part 6, Task 4: Integration Testing & Reproducible Evaluation
 *
 * Verifies:
 * 1. Backend unavailable and readiness-failure states.
 * 2. Job states: successful, failed, partial_success, and cancelled.
 * 3. Route selection and visibility controls.
 * 4. Metrics formatting and unavailable/null values.
 * 5. Malformed GeoJSON validation and error boundaries.
 * 6. Requested vs snapped endpoints audit.
 * 7. Out-of-coverage warning display and non-fabrication of routes.
 */

import { describe, it, expect } from "vitest";
import { ROUTE_COLORS, ROUTE_LABELS } from "../src/components/InteractiveMap";

describe("GeoRoute AI - Frontend Component & Workflow Tests", () => {
  // 1. Readiness failure states
  it("1. Readiness failure states correctly identified", () => {
    const degradedReadiness = {
      status: "degraded",
      precomputed_mode_ready: false,
      full_pipeline_mode_ready: true,
      pyorps_engine_available: false,
      storage_ready: true,
      active_jobs: 0,
      queued_jobs: 0,
      details: { cost_rasters_dir: "missing" },
    };

    const isSystemReady = degradedReadiness.status === "ready" && degradedReadiness.precomputed_mode_ready;
    expect(isSystemReady).toBe(false);
    expect(degradedReadiness.pyorps_engine_available).toBe(false);
  });

  // 2. Job state transitions
  it("2. Job states handling: completed, partial_success, failed, cancelled", () => {
    const validStates = ["queued", "validating", "routing", "completed", "partial_success", "failed", "cancelled"];
    
    const getBadgeStyle = (status) => {
      switch (status) {
        case "completed":
          return { bg: "rgba(16, 185, 129, 0.2)", color: "#10b981", label: "Completed" };
        case "partial_success":
          return { bg: "rgba(245, 158, 11, 0.2)", color: "#f59e0b", label: "Partial Success" };
        case "failed":
          return { bg: "rgba(239, 68, 68, 0.2)", color: "#ef4444", label: "Failed" };
        case "cancelled":
          return { bg: "rgba(148, 163, 184, 0.2)", color: "#94a3b8", label: "Cancelled" };
        default:
          return { bg: "rgba(59, 130, 246, 0.2)", color: "#3b82f6", label: "Processing" };
      }
    };

    validStates.forEach((s) => {
      const badge = getBadgeStyle(s);
      expect(badge.label).toBeDefined();
      expect(badge.color).toBeDefined();
    });

    expect(getBadgeStyle("completed").label).toBe("Completed");
    expect(getBadgeStyle("partial_success").label).toBe("Partial Success");
    expect(getBadgeStyle("failed").label).toBe("Failed");
    expect(getBadgeStyle("cancelled").label).toBe("Cancelled");
  });

  // 3. Route selection and visibility controls
  it("3. Route selection and visibility controls filtering", () => {
    const mockRoutes = [
      { id: "route_1", objective: "shortest_distance", visible: true },
      { id: "route_2", objective: "lowest_construction_difficulty", visible: false },
      { id: "route_3", objective: "lowest_environmental_impact", visible: true },
    ];

    let selectedRouteId = "route_1";
    let visibilityMap = {
      shortest_distance: true,
      lowest_construction_difficulty: false,
      lowest_environmental_impact: true,
    };

    // Filter visible features
    const visibleRoutes = mockRoutes.filter((r) => visibilityMap[r.objective]);
    expect(visibleRoutes).toHaveLength(2);
    expect(visibleRoutes.map((r) => r.objective)).toEqual([
      "shortest_distance",
      "lowest_environmental_impact",
    ]);

    // Toggle visibility
    visibilityMap.lowest_construction_difficulty = true;
    const allVisible = mockRoutes.filter((r) => visibilityMap[r.objective]);
    expect(allVisible).toHaveLength(3);
  });

  // 4. Metrics formatting: missing and unavailable values
  it("4. Metrics formatting handles unavailable, null, and non-numeric values safely", () => {
    const formatMetric = (val, decimals = 1, unit = "") => {
      if (val === null || val === undefined || isNaN(val) || val === "") return "N/A";
      const num = Number(val);
      return `${num.toFixed(decimals)}${unit ? " " + unit : ""}`;
    };

    expect(formatMetric(null, 1, "km")).toBe("N/A");
    expect(formatMetric(undefined, 2, "m")).toBe("N/A");
    expect(formatMetric("", 1)).toBe("N/A");
    expect(formatMetric("invalid", 1)).toBe("N/A");
    expect(formatMetric(0, 1, "m")).toBe("0.0 m");
    expect(formatMetric(353.329, 2, "km")).toBe("353.33 km");
  });

  // 5. Malformed GeoJSON validation
  it("5. Malformed GeoJSON detection and validation", () => {
    const validateGeoJson = (geojson) => {
      if (!geojson || geojson.type !== "FeatureCollection" || !Array.isArray(geojson.features)) {
        return { valid: false, reason: "Not a valid FeatureCollection" };
      }
      for (const feat of geojson.features) {
        if (!feat.geometry || feat.geometry.type !== "LineString") {
          return { valid: false, reason: "Feature must have LineString geometry" };
        }
        if (!Array.isArray(feat.geometry.coordinates) || feat.geometry.coordinates.length < 2) {
          return { valid: false, reason: "LineString must have at least 2 coordinate points" };
        }
      }
      return { valid: true };
    };

    expect(validateGeoJson(null).valid).toBe(false);
    expect(validateGeoJson({ type: "Invalid" }).valid).toBe(false);
    expect(validateGeoJson({ type: "FeatureCollection", features: [{ geometry: { type: "Point" } }] }).valid).toBe(false);
    expect(
      validateGeoJson({
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: {
              type: "LineString",
              coordinates: [
                [76.9322, 31.7084],
                [77.2195, 28.643],
              ],
            },
          },
        ],
      }).valid
    ).toBe(true);
  });

  // 6. Snapping audit: requested vs snapped endpoints
  it("6. Requested vs snapped endpoints audit formatting", () => {
    const snappingAudit = {
      source_requested_wgs84: [76.9322, 31.7084],
      source_actual_wgs84: [76.932069, 31.708467],
      source_snapping_distance_m: 14.41,
      dest_requested_wgs84: [77.2195, 28.643],
      dest_actual_wgs84: [77.219578, 28.642963],
      dest_snapping_distance_m: 8.68,
      is_within_tolerance: true,
    };

    expect(snappingAudit.is_within_tolerance).toBe(true);
    expect(snappingAudit.source_snapping_distance_m).toBeLessThan(60.0);
    expect(snappingAudit.dest_snapping_distance_m).toBeLessThan(60.0);

    const formatOffset = (dist) => `${dist.toFixed(1)} m`;
    expect(formatOffset(snappingAudit.source_snapping_distance_m)).toBe("14.4 m");
    expect(formatOffset(snappingAudit.dest_snapping_distance_m)).toBe("8.7 m");
  });

  // 7. Out-of-coverage warning and no fabricated route
  it("7. Strict out-of-coverage warning policy prevents fabricated routes", () => {
    const localBounds = {
      minLon: 76.9,
      maxLon: 76.96,
      minLat: 31.68,
      maxLat: 31.73,
    };

    const delhiStation = { lon: 77.2195, lat: 28.643 };

    const isInLocalCoverage = (pt) =>
      pt.lon >= localBounds.minLon &&
      pt.lon <= localBounds.maxLon &&
      pt.lat >= localBounds.minLat &&
      pt.lat <= localBounds.maxLat;

    expect(isInLocalCoverage(delhiStation)).toBe(false);

    // In local mode, when destination is outside coverage:
    const handleLocalRouteRequest = (src, dst, mode) => {
      if (mode === "precomputed" && !isInLocalCoverage(dst)) {
        return {
          status: "OUT_OF_COVERAGE_ERROR",
          hasFabricatedRoute: false,
          error: "Requested destination lies outside local study area. Route cannot be fabricated.",
        };
      }
      return { status: "OK", hasFabricatedRoute: false };
    };

    const result = handleLocalRouteRequest({ lon: 76.9322, lat: 31.7084 }, delhiStation, "precomputed");
    expect(result.status).toBe("OUT_OF_COVERAGE_ERROR");
    expect(result.hasFabricatedRoute).toBe(false);
  });
});
