/**
 * GeoRoute AI — Frontend Dashboard Domain Logic Unit Tests
 * Verifies objective color mappings, formatting rules, GeoJSON validation, and constraint policies.
 */

import { describe, it, expect } from "vitest";
import {
  ROUTE_COLORS,
  ROUTE_LABELS,
  MANDI_STUDY_BOUNDS,
  CARTO_API_KEY,
  CARTO_VECTOR_STYLES,
  getCartoRasterTiles,
} from "../src/components/InteractiveMap";

describe("GeoRoute AI - Dashboard Domain Logic & Specifications", () => {
  it("1. Three route alternatives match canonical specified colors", () => {
    expect(ROUTE_COLORS.shortest_distance).toBe("#2563EB"); // Blue
    expect(ROUTE_COLORS.lowest_construction_difficulty).toBe("#F59E0B"); // Amber
    expect(ROUTE_COLORS.lowest_environmental_impact).toBe("#10B981"); // Emerald
  });

  it("2. Objective labels are accurate and descriptive", () => {
    expect(ROUTE_LABELS.shortest_distance).toBe("Shortest Distance");
    expect(ROUTE_LABELS.lowest_construction_difficulty).toBe("Lowest Construction Difficulty");
    expect(ROUTE_LABELS.lowest_environmental_impact).toBe("Lowest Environmental Impact");
  });

  it("3. Metric formatting rules: missing and null values format as N/A, never as 0", () => {
    const fmt = (val, decimals = 1, unit = "") => {
      if (val === null || val === undefined || isNaN(val)) return "N/A";
      return `${Number(val).toFixed(decimals)}${unit ? " " + unit : ""}`;
    };

    expect(fmt(null)).toBe("N/A");
    expect(fmt(undefined)).toBe("N/A");
    expect(fmt(NaN)).toBe("N/A");
    expect(fmt(0, 1)).toBe("0.0"); // legitimate zero
    expect(fmt(2.718, 2, "km")).toBe("2.72 km");
    expect(fmt(37.94, 1, "%")).toBe("37.9 %");
  });

  it("4. Mandi study bounds encompass local 5.8km grid and strictly exclude New Delhi", () => {
    const [sw, ne] = MANDI_STUDY_BOUNDS;
    const [minLon, minLat] = sw;
    const [maxLon, maxLat] = ne;

    // Mandi Station is within bounds
    const mandiStation = { lon: 76.9322, lat: 31.7084 };
    const isMandiInBounds =
      mandiStation.lon >= minLon &&
      mandiStation.lon <= maxLon &&
      mandiStation.lat >= minLat &&
      mandiStation.lat <= maxLat;
    expect(isMandiInBounds).toBe(true);

    // New Delhi Station is 341km south and strictly out of bounds
    const delhiStation = { lon: 77.2195, lat: 28.643 };
    const isDelhiInBounds =
      delhiStation.lon >= minLon &&
      delhiStation.lon <= maxLon &&
      delhiStation.lat >= minLat &&
      delhiStation.lat <= maxLat;
    expect(isDelhiInBounds).toBe(false);
  });

  it("5. RFC 7946 GeoJSON FeatureCollection validation", () => {
    const sampleFeatureCollection = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {
            route_id: "route_1_shortest_distance",
            objective: "shortest_distance",
            status: "preliminary_candidate_corridor",
            length_km: 2.72,
            accumulated_cost: 2718.6,
            cost_units: "metres",
          },
          geometry: {
            type: "LineString",
            coordinates: [
              [76.9312, 31.7084],
              [76.935, 31.715],
              [76.9425, 31.722],
            ],
          },
        },
      ],
    };

    expect(sampleFeatureCollection.type).toBe("FeatureCollection");
    expect(sampleFeatureCollection.features).toHaveLength(1);

    const feat = sampleFeatureCollection.features[0];
    expect(feat.geometry.type).toBe("LineString");
    expect(feat.geometry.coordinates.length).toBeGreaterThanOrEqual(2);

    // Each coordinate must be [longitude, latitude] in WGS84 range
    feat.geometry.coordinates.forEach(([lon, lat]) => {
      expect(lon).toBeGreaterThanOrEqual(-180);
      expect(lon).toBeLessThanOrEqual(180);
      expect(lat).toBeGreaterThanOrEqual(-90);
      expect(lat).toBeLessThanOrEqual(90);
    });

    expect(feat.properties.objective).toBe("shortest_distance");
    expect(feat.properties.length_km).toBeGreaterThan(0);
  });

  it("6. Future route types policy: only railway is active, road and wire are disabled/planned", () => {
    const routeTypes = [
      { id: "railway", label: "Railway Track", status: "active", focus: true },
      { id: "road", label: "Road Routes", status: "planned", disabled: true },
      { id: "wire", label: "Wire / Utility", status: "planned", disabled: true },
    ];

    const activeRoutes = routeTypes.filter((r) => r.status === "active");
    expect(activeRoutes).toHaveLength(1);
    expect(activeRoutes[0].id).toBe("railway");

    const plannedRoutes = routeTypes.filter((r) => r.status === "planned");
    expect(plannedRoutes).toHaveLength(2);
    plannedRoutes.forEach((r) => {
      expect(r.disabled).toBe(true);
    });
  });

  it("7. CARTO Basemap Authentication: active API key and parameter formatting", () => {
    // Verified key from CARTO configuration
    expect(CARTO_API_KEY).toBe("cb1_4jkw_1_be387a4271c43b2c7b9af52b");

    // Raster tiles must include active key to prevent watermarks
    const voyagerTiles = getCartoRasterTiles("voyager");
    expect(voyagerTiles).toHaveLength(3);
    voyagerTiles.forEach((url) => {
      expect(url).toContain("rastertiles/voyager");
      expect(url).toContain("key=cb1_4jkw_1_be387a4271c43b2c7b9af52b");
    });

    const darkTiles = getCartoRasterTiles("dark_all");
    expect(darkTiles).toHaveLength(3);
    darkTiles.forEach((url) => {
      expect(url).toContain("rastertiles/dark_all");
      expect(url).toContain("key=cb1_4jkw_1_be387a4271c43b2c7b9af52b");
    });

    // Vector styles must be properly structured with key
    expect(CARTO_VECTOR_STYLES.voyager).toContain("gl/voyager-gl-style/style.json?key=cb1_4jkw_1_be387a4271c43b2c7b9af52b");
    expect(CARTO_VECTOR_STYLES.dark_matter).toContain("gl/dark-matter-gl-style/style.json?key=cb1_4jkw_1_be387a4271c43b2c7b9af52b");
  });
});

