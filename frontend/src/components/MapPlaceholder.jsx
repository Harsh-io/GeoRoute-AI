import React from "react";
import { Layers, Compass, Maximize2, Crosshair, Map } from "lucide-react";

export default function MapPlaceholder({ endpoints, activeJob }) {
  const source = endpoints?.source;
  const destination = endpoints?.destination;

  return (
    <div
      style={{
        flex: 1,
        position: "relative",
        background: "radial-gradient(ellipse at center, #0f1f2e 0%, #080e16 100%)",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-lg)",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        minHeight: "420px",
      }}
    >
      {/* Background GIS Grid Pattern */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: `
            linear-gradient(rgba(20, 184, 166, 0.05) 1px, transparent 1px),
            linear-gradient(90deg, rgba(20, 184, 166, 0.05) 1px, transparent 1px)
          `,
          backgroundSize: "40px 40px",
          pointerEvents: "none",
        }}
      />

      {/* Top HUD: Spatial Reference & Extents */}
      <div
        style={{
          position: "absolute",
          top: "14px",
          left: "16px",
          right: "16px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          zIndex: 5,
          pointerEvents: "none",
        }}
      >
        {/* Left HUD: CRS & System Mode */}
        <div
          style={{
            background: "rgba(12, 20, 31, 0.85)",
            backdropFilter: "blur(6px)",
            border: "1px solid rgba(255, 255, 255, 0.1)",
            borderRadius: "var(--radius-md)",
            padding: "6px 12px",
            display: "flex",
            alignItems: "center",
            gap: "10px",
            pointerEvents: "auto",
          }}
        >
          <Compass size={14} color="var(--turquoise)" />
          <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>
            <span style={{ color: "#ffffff", fontWeight: 600 }}>CRS:</span> EPSG:32643 (UTM 43N) · <span style={{ color: "#ffffff", fontWeight: 600 }}>Display:</span> EPSG:4326
          </div>
        </div>

        {/* Right HUD: Study Grid Dimensions */}
        <div
          style={{
            background: "rgba(12, 20, 31, 0.85)",
            backdropFilter: "blur(6px)",
            border: "1px solid rgba(255, 255, 255, 0.1)",
            borderRadius: "var(--radius-md)",
            padding: "6px 12px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
            fontSize: "11px",
            color: "var(--text-muted)",
            pointerEvents: "auto",
          }}
        >
          <Layers size={13} color="var(--cyan-bright)" />
          <span>Mandi Grid: 579 × 565 cells (10.0m res)</span>
        </div>
      </div>

      {/* Center Viewport Message */}
      <div
        style={{
          margin: "auto",
          textAlign: "center",
          zIndex: 5,
          maxWidth: "480px",
          padding: "20px",
        }}
      >
        <div
          style={{
            width: "56px",
            height: "56px",
            borderRadius: "14px",
            background: "rgba(13, 148, 136, 0.15)",
            border: "1px solid rgba(20, 184, 166, 0.3)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            margin: "0 auto 14px",
            boxShadow: "0 0 24px rgba(20, 184, 166, 0.2)",
          }}
        >
          <Map size={28} color="var(--turquoise)" />
        </div>

        <h3
          style={{
            fontFamily: "var(--font-display)",
            fontSize: "16px",
            fontWeight: 700,
            color: "#ffffff",
            marginBottom: "6px",
          }}
        >
          Interactive GIS Viewport
        </h3>
        <p style={{ fontSize: "12px", color: "var(--text-muted)", lineHeight: "1.5" }}>
          MapLibre GL tile layers, raster cost surface visualizations, and 3-corridor overlays are reserved for <strong>Task 3</strong>.
        </p>

        {source && destination && (
          <div
            style={{
              marginTop: "16px",
              padding: "10px 14px",
              borderRadius: "var(--radius-md)",
              background: "rgba(12, 20, 31, 0.7)",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              display: "inline-flex",
              flexDirection: "column",
              gap: "4px",
              textAlign: "left",
              fontSize: "11px",
            }}
          >
            <div style={{ color: "#38bdf8" }}>
              <strong>Origin:</strong> {source.name || "Origin"} ({source.longitude.toFixed(4)}°E, {source.latitude.toFixed(4)}°N)
            </div>
            <div style={{ color: "#f43f5e" }}>
              <strong>Destination:</strong> {destination.name || "Destination"} ({destination.longitude.toFixed(4)}°E, {destination.latitude.toFixed(4)}°N)
            </div>
          </div>
        )}
      </div>

      {/* Bottom HUD: Status & Scale */}
      <div
        style={{
          position: "absolute",
          bottom: "14px",
          left: "16px",
          right: "16px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          zIndex: 5,
          pointerEvents: "none",
        }}
      >
        <div
          style={{
            background: "rgba(12, 20, 31, 0.85)",
            backdropFilter: "blur(6px)",
            border: "1px solid rgba(255, 255, 255, 0.1)",
            borderRadius: "var(--radius-md)",
            padding: "5px 10px",
            fontSize: "11px",
            color: "var(--text-dim)",
            pointerEvents: "auto",
          }}
        >
          {activeJob ? (
            <span>Active Job: <strong style={{ color: "var(--cyan-bright)" }}>{activeJob.job_id}</strong> ({activeJob.status})</span>
          ) : (
            <span>Ready for Corridor Submission</span>
          )}
        </div>

        <div
          style={{
            background: "rgba(12, 20, 31, 0.85)",
            backdropFilter: "blur(6px)",
            border: "1px solid rgba(255, 255, 255, 0.1)",
            borderRadius: "var(--radius-md)",
            padding: "5px 10px",
            fontSize: "11px",
            color: "var(--text-dim)",
            pointerEvents: "auto",
          }}
        >
          Scale: 10m Ground Resolution (SRTM / Copernicus HMA 30m)
        </div>
      </div>
    </div>
  );
}
