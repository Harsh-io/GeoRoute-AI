import React from "react";
import { X, Layers, CheckCircle2, ShieldCheck, Database, Info, FileSpreadsheet } from "lucide-react";

export default function MapLayersModal({ isOpen, onClose }) {
  if (!isOpen) return null;

  const VERIFIED_LAYERS = [
    {
      category: "Terrain & Elevation",
      layers: [
        {
          id: "dem",
          name: "Digital Elevation Model (DEM)",
          source: "SRTM / Copernicus 30m HMA Resampled",
          res: "10.0m",
          file: "dem.tif",
          description: "Continuously aligned elevation surface covering Mandi study area (579 × 565 cells).",
          status: "Precomputed & Aligned",
        },
        {
          id: "slope_percent",
          name: "Terrain Slope (Percent & Degrees)",
          source: "Horn's 3×3 Finite-Difference Method",
          res: "10.0m",
          file: "slope_percent.tif / slope_degrees.tif",
          description: "Engineered slope gradient surface penalizing extreme grades (>15% and >25%).",
          status: "Precomputed & Aligned",
        },
      ],
    },
    {
      category: "Land Cover & Environmental Sensitivity",
      layers: [
        {
          id: "landcover",
          name: "Classified Land Cover",
          source: "ESA WorldCover 10m 2021",
          res: "10.0m",
          file: "classified_landcover.tif",
          description: "Discrete landcover classes: Tree cover (62-73%), Built-up, Cropland, Grassland, Bare ground.",
          status: "Precomputed & Aligned",
        },
        {
          id: "ndvi",
          name: "Canopy Density (NDVI)",
          source: "Sentinel-2 Multi-Spectral Harmonized",
          res: "10.0m",
          file: "ndvi.tif / forest_mask.tif",
          description: "Normalized Difference Vegetation Index weighting virgin forest vs degraded land.",
          status: "Precomputed & Aligned",
        },
        {
          id: "water_wetland",
          name: "Water Bodies & Wetlands",
          source: "OSM Hydrology & ESA Wetlands",
          res: "10.0m",
          file: "water_mask.tif / wetland_mask.tif",
          description: "Hard exclusion buffers and bridge crossing friction penalties.",
          status: "Precomputed & Aligned",
        },
      ],
    },
    {
      category: "Infrastructure & Hard Constraints",
      layers: [
        {
          id: "physical_obstacles",
          name: "Buildings & Infrastructure Obstacles",
          source: "OSM Vector Features & Built-up Rasters",
          res: "10.0m",
          file: "combined_obstacle_mask.tif",
          description: "Building footprints and physical infrastructure enforced as unroutable (friction = ∞).",
          status: "Precomputed & Aligned",
        },
        {
          id: "cost_surfaces",
          name: "Multi-Objective Cost Surfaces (3 Rasters)",
          source: "Synthesized Friction Pipeline (Part 3)",
          res: "10.0m",
          file: "distance_friction.tif, construction_friction.tif, environmental_friction.tif",
          description: "Quantized uint16 cost surfaces input directly into PYORPS Cython Dijkstra graph.",
          status: "Active in Engine",
        },
      ],
    },
  ];

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(0, 0, 0, 0.75)",
        backdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
        padding: "20px",
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "var(--bg-panel)",
          border: "1px solid var(--border-strong)",
          borderRadius: "var(--radius-lg)",
          width: "100%",
          maxWidth: "760px",
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 10px 40px rgba(0, 0, 0, 0.6)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div
          style={{
            padding: "16px 20px",
            borderBottom: "1px solid var(--border-subtle)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <Layers size={20} color="var(--turquoise)" />
            <div>
              <h3 style={{ fontSize: "15px", fontWeight: 700, color: "#ffffff" }}>
                Verified Geospatial Raster & Feature Layers
              </h3>
              <p style={{ fontSize: "11.5px", color: "var(--text-muted)" }}>
                Study Area: Mandi Grid (5.79 × 5.65 km · EPSG:32643 UTM 43N · 10m resolution)
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="btn btn-secondary btn-sm"
            style={{ padding: "4px 8px" }}
          >
            <X size={15} />
          </button>
        </div>

        {/* Modal Content */}
        <div style={{ padding: "20px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "18px" }}>
          {/* Architectural Notice regarding Tile Serving */}
          <div
            style={{
              background: "rgba(13, 148, 136, 0.12)",
              border: "1px solid rgba(20, 184, 166, 0.25)",
              borderRadius: "var(--radius-md)",
              padding: "12px 14px",
              display: "flex",
              alignItems: "flex-start",
              gap: "10px",
            }}
          >
            <Info size={18} color="var(--turquoise)" style={{ flexShrink: 0, marginTop: "2px" }} />
            <div style={{ fontSize: "11.5px", color: "#e2e8f0", lineHeight: "1.4" }}>
              <strong>Raster Serving Notice:</strong> All listed rasters are validated and aligned on the backend server. To maintain browser performance and low memory footprints, raw multi-megabyte GeoTIFFs are processed into vector corridor graphs server-side. Direct WebGL XYZ raster tile serving (`/api/v1/layers/{id}/tiles`) is documented below as the recommended backend extension.
            </div>
          </div>

          {/* Categories & Layer Cards */}
          {VERIFIED_LAYERS.map((cat, idx) => (
            <div key={idx}>
              <h4
                style={{
                  fontSize: "12px",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  color: "var(--turquoise)",
                  marginBottom: "8px",
                }}
              >
                {cat.category}
              </h4>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                {cat.layers.map((l) => (
                  <div
                    key={l.id}
                    style={{
                      background: "var(--bg-panel-alt)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "var(--radius-md)",
                      padding: "10px 14px",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: "14px",
                    }}
                  >
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <span style={{ fontWeight: 600, fontSize: "12.5px", color: "var(--text-main)" }}>
                          {l.name}
                        </span>
                        <code style={{ fontSize: "10.5px", color: "var(--text-dim)" }}>{l.file}</code>
                      </div>
                      <p style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                        {l.description}
                      </p>
                      <div style={{ fontSize: "10.5px", color: "var(--text-dim)", marginTop: "4px" }}>
                        Source: {l.source} · Cell Size: {l.res}
                      </div>
                    </div>

                    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "4px" }}>
                      <span className="badge badge-emerald" style={{ fontSize: "10px" }}>
                        <CheckCircle2 size={11} />
                        <span>{l.status}</span>
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Modal Footer */}
        <div
          style={{
            padding: "12px 20px",
            borderTop: "1px solid var(--border-subtle)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "var(--bg-panel-alt)",
          }}
        >
          <span style={{ fontSize: "11px", color: "var(--text-dim)" }}>
            CRS: EPSG:32643 (UTM Zone 43N) · Ground Resolution: 10.0m
          </span>
          <button className="btn btn-secondary btn-sm" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
