import React, { useEffect, useRef, useState, useCallback } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  Compass,
  Layers,
  Maximize2,
  Eye,
  EyeOff,
  Crosshair,
  Info,
  MapPin,
  AlertCircle,
} from "lucide-react";

// Canonical Objective Colors mandated by specification
export const ROUTE_COLORS = {
  shortest_distance: "#2563EB", // Blue
  lowest_construction_difficulty: "#F59E0B", // Amber
  lowest_environmental_impact: "#10B981", // Emerald
};

export const ROUTE_LABELS = {
  shortest_distance: "Shortest Distance",
  lowest_construction_difficulty: "Lowest Construction Difficulty",
  lowest_environmental_impact: "Lowest Environmental Impact",
};

// Mandi Regional Grid bounds from API capabilities (approx WGS84)
export const MANDI_STUDY_BOUNDS = [
  [76.90, 31.68], // Southwest
  [76.96, 31.73], // Northeast
];

// CARTO Basemap Authentication Key
export const CARTO_API_KEY =
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_CARTO_API_KEY) ||
  "cb1_4jkw_1_be387a4271c43b2c7b9af52b";

// Vector GL Style URLs (as per CARTO API guidelines for current & future vector styles)
export const CARTO_VECTOR_STYLES = {
  voyager: `https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json?key=${CARTO_API_KEY}`,
  dark_matter: `https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json?key=${CARTO_API_KEY}`,
  positron: `https://basemaps.cartocdn.com/gl/positron-gl-style/style.json?key=${CARTO_API_KEY}`,
};

// Raster tile URLs with active authenticated key parameter to eliminate watermarks
export const getCartoRasterTiles = (style, apiKey = CARTO_API_KEY) => [
  `https://a.basemaps.cartocdn.com/rastertiles/${style}/{z}/{x}/{y}@2x.png?key=${apiKey}`,
  `https://b.basemaps.cartocdn.com/rastertiles/${style}/{z}/{x}/{y}@2x.png?key=${apiKey}`,
  `https://c.basemaps.cartocdn.com/rastertiles/${style}/{z}/{x}/{y}@2x.png?key=${apiKey}`,
];

// Multi-style Basemap definition
const BASEMAP_STYLE = {
  version: 8,
  sources: {
    "carto-dark": {
      type: "raster",
      tiles: getCartoRasterTiles("dark_all"),
      tileSize: 256,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions" target="_blank">CARTO</a>',
    },
    "carto-voyager": {
      type: "raster",
      tiles: getCartoRasterTiles("voyager"),
      tileSize: 256,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions" target="_blank">CARTO</a>',
    },
    "carto-light": {
      type: "raster",
      tiles: getCartoRasterTiles("light_all"),
      tileSize: 256,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions" target="_blank">CARTO</a>',
    },
  },
  layers: [
    {
      id: "background-color",
      type: "background",
      paint: {
        "background-color": "#080d14",
      },
    },
    {
      id: "carto-dark-tiles",
      type: "raster",
      source: "carto-dark",
      minzoom: 0,
      maxzoom: 19,
      layout: {
        visibility: "visible",
      },
    },
    {
      id: "carto-voyager-tiles",
      type: "raster",
      source: "carto-voyager",
      minzoom: 0,
      maxzoom: 19,
      layout: {
        visibility: "none",
      },
    },
    {
      id: "carto-light-tiles",
      type: "raster",
      source: "carto-light",
      minzoom: 0,
      maxzoom: 19,
      layout: {
        visibility: "none",
      },
    },
  ],
};


export default function InteractiveMap({
  routesGeoJson,
  endpoints,
  selectedRouteId,
  onSelectRoute,
  visibleObjectives,
  onToggleObjective,
  showStudyBoundary,
  onToggleStudyBoundary,
  onOpenLayersModal,
}) {
  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const sourceMarkerRef = useRef(null);
  const destMarkerRef = useRef(null);
  const hoverPopupRef = useRef(null);

  const [mapLoaded, setMapLoaded] = useState(false);
  const [mapError, setMapError] = useState(null);
  const [mouseCoords, setMouseCoords] = useState(null);
  const [activeBasemap, setActiveBasemap] = useState("dark_all"); // "dark_all" | "voyager" | "light_all"

  // 1. Initialize MapLibre GL instance
  useEffect(() => {
    if (!mapContainerRef.current) return;

    try {
      const map = new maplibregl.Map({
        container: mapContainerRef.current,
        style: BASEMAP_STYLE,
        center: [76.9312, 31.7084], // Mandi study grid center
        zoom: 13,
        maxZoom: 18,
        minZoom: 9,
        attributionControl: false,
        transformRequest: (url) => {
          if (url && url.includes("cartocdn.com") && !url.includes("key=") && !url.includes("cb1_")) {
            const sep = url.includes("?") ? "&" : "?";
            return { url: `${url}${sep}key=${CARTO_API_KEY}` };
          }
          return { url };
        },
      });

      // Navigation & Scale Controls
      map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "top-right");
      map.addControl(new maplibregl.ScaleControl({ maxWidth: 150, unit: "metric" }), "bottom-right");
      map.addControl(
        new maplibregl.AttributionControl({
          compact: true,
          customAttribution: "GeoRoute AI · SRTM / Copernicus DEM · Mandi Grid",
        }),
        "bottom-right"
      );

      // Coordinate tracking on mouse move
      map.on("mousemove", (e) => {
        setMouseCoords({
          lon: e.lngLat.lng.toFixed(4),
          lat: e.lngLat.lat.toFixed(4),
        });
      });

      map.on("load", () => {
        // Study Area Bounding Box GeoJSON Feature
        const studyBoxGeoJson = {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              properties: {
                name: "Mandi Regional Study Grid (5.79 × 5.65 km)",
                crs: "EPSG:32643 (UTM 43N)",
                resolution: "10.0m ground resolution",
              },
              geometry: {
                type: "Polygon",
                coordinates: [
                  [
                    [76.90, 31.68],
                    [76.96, 31.68],
                    [76.96, 31.73],
                    [76.90, 31.73],
                    [76.90, 31.68],
                  ],
                ],
              },
            },
          ],
        };

        map.addSource("study-boundary-src", {
          type: "geojson",
          data: studyBoxGeoJson,
        });

        // Fill layer
        map.addLayer({
          id: "study-boundary-fill",
          type: "fill",
          source: "study-boundary-src",
          paint: {
            "fill-color": "#14b8a6",
            "fill-opacity": 0.05,
          },
        });

        // Dashed border outline
        map.addLayer({
          id: "study-boundary-line",
          type: "line",
          source: "study-boundary-src",
          paint: {
            "line-color": "#14b8a6",
            "line-width": 2,
            "line-dasharray": [3, 2],
            "line-opacity": 0.85,
          },
        });

        // Source for Corridors
        map.addSource("routes-geojson-src", {
          type: "geojson",
          data: { type: "FeatureCollection", features: [] },
        });

        // 1. Casing / Glow Layer for routes
        map.addLayer({
          id: "routes-glow-layer",
          type: "line",
          source: "routes-geojson-src",
          layout: {
            "line-cap": "round",
            "line-join": "round",
          },
          paint: {
            "line-width": [
              "case",
              ["==", ["get", "route_id"], selectedRouteId || ""],
              10,
              6,
            ],
            "line-color": [
              "match",
              ["get", "objective"],
              "shortest_distance",
              "#2563EB",
              "lowest_construction_difficulty",
              "#F59E0B",
              "lowest_environmental_impact",
              "#10B981",
              "#06b6d4",
            ],
            "line-opacity": [
              "case",
              ["==", ["get", "route_id"], selectedRouteId || ""],
              0.55,
              0.2,
            ],
          },
        });

        // 2. Primary Route Alignment Lines
        map.addLayer({
          id: "routes-line-layer",
          type: "line",
          source: "routes-geojson-src",
          layout: {
            "line-cap": "round",
            "line-join": "round",
          },
          paint: {
            "line-width": [
              "case",
              ["==", ["get", "route_id"], selectedRouteId || ""],
              4.5,
              3.0,
            ],
            "line-color": [
              "match",
              ["get", "objective"],
              "shortest_distance",
              "#2563EB",
              "lowest_construction_difficulty",
              "#F59E0B",
              "lowest_environmental_impact",
              "#10B981",
              "#ffffff",
            ],
            "line-opacity": 0.95,
          },
        });

        // Hover & Click Interactions
        map.on("mouseenter", "routes-line-layer", (e) => {
          map.getCanvas().style.cursor = "pointer";
          const feature = e.features?.[0];
          if (!feature) return;

          const p = feature.properties;
          const label = ROUTE_LABELS[p.objective] || p.objective;
          const color = ROUTE_COLORS[p.objective] || "#06b6d4";

          if (hoverPopupRef.current) hoverPopupRef.current.remove();
          hoverPopupRef.current = new maplibregl.Popup({
            closeButton: false,
            closeOnClick: false,
            offset: 12,
            className: "gis-map-popup",
          })
            .setLngLat(e.lngLat)
            .setHTML(`
              <div style="font-family: inherit; font-size: 11.5px; line-height: 1.4;">
                <div style="font-weight: 700; color: ${color}; margin-bottom: 2px;">${label}</div>
                <div>Length: <strong>${p.length_km ? Number(p.length_km).toFixed(2) : "N/A"} km</strong></div>
                <div>Max Slope: <strong>${p.max_slope_pct ? Number(p.max_slope_pct).toFixed(1) : "N/A"}%</strong></div>
                <div>Status: <span style="color: #34d399;">${p.status || "Evaluated"}</span></div>
              </div>
            `)
            .addTo(map);
        });

        map.on("mouseleave", "routes-line-layer", () => {
          map.getCanvas().style.cursor = "";
          if (hoverPopupRef.current) {
            hoverPopupRef.current.remove();
            hoverPopupRef.current = null;
          }
        });

        map.on("click", "routes-line-layer", (e) => {
          const feature = e.features?.[0];
          if (feature && feature.properties?.route_id) {
            onSelectRoute(feature.properties.route_id);
          }
        });

        setMapLoaded(true);
      });

      mapRef.current = map;

      return () => {
        if (hoverPopupRef.current) hoverPopupRef.current.remove();
        map.remove();
        mapRef.current = null;
      };
    } catch (err) {
      console.error("MapLibre GL initialization error:", err);
      setMapError("Failed to initialize MapLibre GL canvas. WebGL may be disabled.");
    }
  }, []);

  // 1b. Handle Basemap Style Switching (Dark Matter / Voyager / Positron)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;

    const layerMapping = {
      dark_all: "carto-dark-tiles",
      voyager: "carto-voyager-tiles",
      light_all: "carto-light-tiles",
    };

    Object.entries(layerMapping).forEach(([styleKey, layerId]) => {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(
          layerId,
          "visibility",
          styleKey === activeBasemap ? "visible" : "none"
        );
      }
    });

    if (map.getLayer("background-color")) {
      map.setPaintProperty(
        "background-color",
        "background-color",
        activeBasemap === "dark_all" ? "#080d14" : "#f4f6f8"
      );
    }
  }, [activeBasemap, mapLoaded]);

  // 2. Update Study Boundary Visibility
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;

    const visibility = showStudyBoundary ? "visible" : "none";
    if (map.getLayer("study-boundary-fill")) {
      map.setLayoutProperty("study-boundary-fill", "visibility", visibility);
    }
    if (map.getLayer("study-boundary-line")) {
      map.setLayoutProperty("study-boundary-line", "visibility", visibility);
    }
  }, [showStudyBoundary, mapLoaded]);

  // 3. Update Route GeoJSON Source & Visibility Filtering
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;

    const source = map.getSource("routes-geojson-src");
    if (!source) return;

    if (routesGeoJson && routesGeoJson.features) {
      // Filter features based on user-toggled objectives
      const filteredFeatures = routesGeoJson.features.filter((f) =>
        visibleObjectives.includes(f.properties?.objective)
      );

      source.setData({
        type: "FeatureCollection",
        features: filteredFeatures,
      });

      // Fit map bounds to encompass all valid routes if present
      if (filteredFeatures.length > 0) {
        const bounds = new maplibregl.LngLatBounds();
        let validCoords = 0;

        filteredFeatures.forEach((feat) => {
          const coords = feat.geometry?.coordinates || [];
          coords.forEach(([lng, lat]) => {
            if (!isNaN(lng) && !isNaN(lat)) {
              bounds.extend([lng, lat]);
              validCoords++;
            }
          });
        });

        if (validCoords > 0) {
          map.fitBounds(bounds, { padding: 50, maxZoom: 15, duration: 800 });
        }
      }
    } else {
      source.setData({ type: "FeatureCollection", features: [] });
    }
  }, [routesGeoJson, visibleObjectives, mapLoaded]);

  // 4. Update Highlight Styles when Selected Route Changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;

    if (map.getLayer("routes-glow-layer")) {
      map.setPaintProperty("routes-glow-layer", "line-width", [
        "case",
        ["==", ["get", "route_id"], selectedRouteId || ""],
        11,
        6,
      ]);
      map.setPaintProperty("routes-glow-layer", "line-opacity", [
        "case",
        ["==", ["get", "route_id"], selectedRouteId || ""],
        0.6,
        0.2,
      ]);
    }

    if (map.getLayer("routes-line-layer")) {
      map.setPaintProperty("routes-line-layer", "line-width", [
        "case",
        ["==", ["get", "route_id"], selectedRouteId || ""],
        4.5,
        3.0,
      ]);
    }
  }, [selectedRouteId, mapLoaded]);

  // 5. Update Source and Destination Endpoint Markers
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;

    // Remove old markers
    if (sourceMarkerRef.current) sourceMarkerRef.current.remove();
    if (destMarkerRef.current) destMarkerRef.current.remove();

    if (endpoints?.source) {
      const { longitude, latitude, name } = endpoints.source;
      const el = document.createElement("div");
      el.className = "gis-marker-origin";
      el.innerHTML = `
        <div style="width: 24px; height: 24px; border-radius: 50%; background: #38bdf8; border: 2.5px solid #ffffff; box-shadow: 0 0 10px rgba(56, 189, 248, 0.8); display: flex; align-items: center; justify-content: center;">
          <div style="width: 6px; height: 6px; border-radius: 50%; background: #0c141f;"></div>
        </div>
      `;

      sourceMarkerRef.current = new maplibregl.Marker({ element: el })
        .setLngLat([longitude, latitude])
        .setPopup(
          new maplibregl.Popup({ offset: 15 }).setHTML(`
            <div style="font-size: 11.5px; font-weight: 600; color: #38bdf8;">
              Origin: ${name || "Source"}
            </div>
            <div style="font-size: 10.5px; color: #94a3b8;">${longitude.toFixed(4)}°E, ${latitude.toFixed(4)}°N</div>
          `)
        )
        .addTo(map);
    }

    if (endpoints?.destination) {
      const { longitude, latitude, name } = endpoints.destination;
      const el = document.createElement("div");
      el.className = "gis-marker-dest";
      el.innerHTML = `
        <div style="width: 24px; height: 24px; border-radius: 50%; background: #f43f5e; border: 2.5px solid #ffffff; box-shadow: 0 0 10px rgba(244, 63, 94, 0.8); display: flex; align-items: center; justify-content: center;">
          <div style="width: 6px; height: 6px; border-radius: 50%; background: #0c141f;"></div>
        </div>
      `;

      destMarkerRef.current = new maplibregl.Marker({ element: el })
        .setLngLat([longitude, latitude])
        .setPopup(
          new maplibregl.Popup({ offset: 15 }).setHTML(`
            <div style="font-size: 11.5px; font-weight: 600; color: #f43f5e;">
              Destination: ${name || "Target"}
            </div>
            <div style="font-size: 10.5px; color: #94a3b8;">${longitude.toFixed(4)}°E, ${latitude.toFixed(4)}°N</div>
          `)
        )
        .addTo(map);
    }
  }, [endpoints, mapLoaded]);

  // Fit bounds helper to reset view to Mandi Grid
  const handleResetView = useCallback(() => {
    if (!mapRef.current) return;
    mapRef.current.fitBounds(MANDI_STUDY_BOUNDS, { padding: 40, duration: 800 });
  }, []);

  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        minHeight: "440px",
        borderRadius: "var(--radius-lg)",
        overflow: "hidden",
        border: "1px solid var(--border-subtle)",
        background: "#080d14",
      }}
    >
      {/* Map Container */}
      <div ref={mapContainerRef} style={{ width: "100%", height: "100%" }} />

      {/* Map Error Banner */}
      {mapError && (
        <div
          style={{
            position: "absolute",
            top: "20px",
            left: "50%",
            transform: "translateX(-50%)",
            background: "rgba(244, 63, 94, 0.9)",
            color: "#ffffff",
            padding: "8px 14px",
            borderRadius: "var(--radius-md)",
            fontSize: "12px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
            zIndex: 15,
          }}
        >
          <AlertCircle size={15} />
          <span>{mapError}</span>
        </div>
      )}

      {/* Top-Left HUD: CRS & Geographic Coordinates Readout */}
      <div
        style={{
          position: "absolute",
          top: "12px",
          left: "14px",
          display: "flex",
          flexDirection: "column",
          gap: "6px",
          zIndex: 10,
          pointerEvents: "auto",
        }}
      >
        <div
          style={{
            background: "rgba(12, 20, 31, 0.88)",
            backdropFilter: "blur(6px)",
            border: "1px solid rgba(255, 255, 255, 0.12)",
            borderRadius: "var(--radius-md)",
            padding: "6px 10px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
            fontSize: "11px",
            color: "var(--text-muted)",
          }}
        >
          <Compass size={13} color="var(--turquoise)" />
          <span>
            <strong style={{ color: "#ffffff" }}>CRS:</strong> EPSG:32643 UTM 43N
          </span>
          <span style={{ color: "rgba(255,255,255,0.2)" }}>|</span>
          <span>
            {mouseCoords ? `${mouseCoords.lon}°E, ${mouseCoords.lat}°N` : "76.9312°E, 31.7084°N"}
          </span>
        </div>
      </div>

      {/* Top-Right HUD Controls: Reset View & Terrain Layers */}
      <div
        style={{
          position: "absolute",
          top: "12px",
          right: "52px", // next to maplibre nav controls
          display: "flex",
          alignItems: "center",
          gap: "6px",
          zIndex: 10,
          pointerEvents: "auto",
        }}
      >
        <button
          className="btn btn-secondary btn-sm"
          onClick={handleResetView}
          title="Reset View to Mandi Study Area Boundary"
          style={{ padding: "5px 9px", fontSize: "11.5px" }}
        >
          <Maximize2 size={12} />
          <span>Fit Extent</span>
        </button>

        <button
          className="btn btn-secondary btn-sm"
          onClick={onOpenLayersModal}
          title="Inspect available terrain, obstacle, and cost surface rasters"
          style={{ padding: "5px 9px", fontSize: "11.5px" }}
        >
          <Layers size={12} color="var(--turquoise)" />
          <span>Terrain Layers</span>
        </button>

        {/* Basemap Switcher (Dark Matter / Voyager / Positron) */}
        <div
          style={{
            display: "inline-flex",
            background: "rgba(12, 20, 31, 0.9)",
            border: "1px solid rgba(255, 255, 255, 0.14)",
            borderRadius: "var(--radius-sm)",
            padding: "2px",
            backdropFilter: "blur(6px)",
          }}
          title="Switch CARTO Basemap (API Key Authenticated)"
        >
          <button
            type="button"
            style={{
              background: activeBasemap === "dark_all" ? "var(--teal-primary)" : "transparent",
              color: activeBasemap === "dark_all" ? "#ffffff" : "var(--text-dim)",
              border: "none",
              padding: "3px 8px",
              fontSize: "11px",
              fontWeight: 500,
              borderRadius: "3px",
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
            onClick={() => setActiveBasemap("dark_all")}
            title="Carto Dark Matter (Dark high-contrast mode)"
          >
            Dark
          </button>
          <button
            type="button"
            style={{
              background: activeBasemap === "voyager" ? "var(--teal-primary)" : "transparent",
              color: activeBasemap === "voyager" ? "#ffffff" : "var(--text-dim)",
              border: "none",
              padding: "3px 8px",
              fontSize: "11px",
              fontWeight: 500,
              borderRadius: "3px",
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
            onClick={() => setActiveBasemap("voyager")}
            title="Carto Voyager (Roads, terrain & city detail)"
          >
            Voyager
          </button>
          <button
            type="button"
            style={{
              background: activeBasemap === "light_all" ? "var(--teal-primary)" : "transparent",
              color: activeBasemap === "light_all" ? "#ffffff" : "var(--text-dim)",
              border: "none",
              padding: "3px 8px",
              fontSize: "11px",
              fontWeight: 500,
              borderRadius: "3px",
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
            onClick={() => setActiveBasemap("light_all")}
            title="Carto Positron (Light minimalist mode)"
          >
            Light
          </button>
        </div>
      </div>

      {/* Floating Interactive Route Legend (Bottom Left) */}
      <div
        style={{
          position: "absolute",
          bottom: "16px",
          left: "14px",
          background: "rgba(12, 20, 31, 0.92)",
          backdropFilter: "blur(8px)",
          border: "1px solid rgba(255, 255, 255, 0.12)",
          borderRadius: "var(--radius-md)",
          padding: "10px 14px",
          zIndex: 10,
          display: "flex",
          flexDirection: "column",
          gap: "8px",
          minWidth: "250px",
          pointerEvents: "auto",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid rgba(255,255,255,0.08)", paddingBottom: "5px" }}>
          <span style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--turquoise)" }}>
            Corridor Legend
          </span>
          <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>
            {routesGeoJson?.features?.length || 0} Routes
          </span>
        </div>

        {/* Route 1: Shortest Distance */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            fontSize: "11.5px",
            cursor: "pointer",
          }}
          onClick={() => onToggleObjective("shortest_distance")}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span
              style={{
                width: "16px",
                height: "4px",
                borderRadius: "2px",
                backgroundColor: ROUTE_COLORS.shortest_distance,
                display: "inline-block",
              }}
            />
            <span style={{ color: visibleObjectives.includes("shortest_distance") ? "#ffffff" : "var(--text-dim)" }}>
              Shortest Distance
            </span>
          </div>
          {visibleObjectives.includes("shortest_distance") ? (
            <Eye size={13} color="var(--text-muted)" />
          ) : (
            <EyeOff size={13} color="var(--text-dim)" />
          )}
        </div>

        {/* Route 2: Lowest Construction Difficulty */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            fontSize: "11.5px",
            cursor: "pointer",
          }}
          onClick={() => onToggleObjective("lowest_construction_difficulty")}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span
              style={{
                width: "16px",
                height: "4px",
                borderRadius: "2px",
                backgroundColor: ROUTE_COLORS.lowest_construction_difficulty,
                display: "inline-block",
              }}
            />
            <span style={{ color: visibleObjectives.includes("lowest_construction_difficulty") ? "#ffffff" : "var(--text-dim)" }}>
              Construction Difficulty
            </span>
          </div>
          {visibleObjectives.includes("lowest_construction_difficulty") ? (
            <Eye size={13} color="var(--text-muted)" />
          ) : (
            <EyeOff size={13} color="var(--text-dim)" />
          )}
        </div>

        {/* Route 3: Lowest Environmental Impact */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            fontSize: "11.5px",
            cursor: "pointer",
          }}
          onClick={() => onToggleObjective("lowest_environmental_impact")}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span
              style={{
                width: "16px",
                height: "4px",
                borderRadius: "2px",
                backgroundColor: ROUTE_COLORS.lowest_environmental_impact,
                display: "inline-block",
              }}
            />
            <span style={{ color: visibleObjectives.includes("lowest_environmental_impact") ? "#ffffff" : "var(--text-dim)" }}>
              Environmental Impact
            </span>
          </div>
          {visibleObjectives.includes("lowest_environmental_impact") ? (
            <Eye size={13} color="var(--text-muted)" />
          ) : (
            <EyeOff size={13} color="var(--text-dim)" />
          )}
        </div>

        {/* Study Grid Boundary Toggle */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            fontSize: "11px",
            borderTop: "1px solid rgba(255,255,255,0.08)",
            paddingTop: "6px",
            cursor: "pointer",
          }}
          onClick={onToggleStudyBoundary}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span
              style={{
                width: "16px",
                height: "3px",
                borderTop: "2px dashed #14b8a6",
                display: "inline-block",
              }}
            />
            <span style={{ color: showStudyBoundary ? "var(--turquoise)" : "var(--text-dim)" }}>
              Mandi 5×5 km Grid
            </span>
          </div>
          {showStudyBoundary ? (
            <Eye size={13} color="var(--turquoise)" />
          ) : (
            <EyeOff size={13} color="var(--text-dim)" />
          )}
        </div>
      </div>
    </div>
  );
}
