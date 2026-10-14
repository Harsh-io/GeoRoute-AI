import React, { useState } from "react";
import RouteComparisonTable from "./RouteComparisonTable";
import {
  Download,
  FileCode,
  ShieldAlert,
  ChevronDown,
  ChevronUp,
  Info,
} from "lucide-react";

export default function ResultsPanel({
  result,
  geojson,
  selectedRouteId,
  onSelectRoute,
  onDownloadGeojson,
}) {
  const [showRawJson, setShowRawJson] = useState(false);

  if (!result) {
    return (
      <div
        style={{
          background: "var(--bg-panel)",
          borderRadius: "var(--radius-lg)",
          border: "1px solid var(--border-subtle)",
          padding: "20px",
          textAlign: "center",
          color: "var(--text-muted)",
        }}
      >
        <Info size={22} style={{ margin: "0 auto 8px", opacity: 0.5 }} />
        <h4 style={{ fontSize: "13px", fontWeight: 600, color: "var(--text-main)" }}>
          No Route Corridors Generated Yet
        </h4>
        <p style={{ fontSize: "11.5px", marginTop: "4px" }}>
          Select endpoints in the Planning Panel and click <strong>Generate Candidate Corridors</strong> to compute multi-objective alignments across the Mandi study grid.
        </p>
      </div>
    );
  }

  const routes = result.routes || [];

  return (
    <div
      style={{
        background: "var(--bg-panel)",
        borderRadius: "var(--radius-lg)",
        border: "1px solid var(--border-subtle)",
        display: "flex",
        flexDirection: "column",
        gap: "14px",
        padding: "16px 20px",
      }}
    >
      {/* Header bar with summary & download actions */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "10px",
          borderBottom: "1px solid var(--border-subtle)",
          paddingBottom: "12px",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <h3 style={{ fontSize: "14px", fontWeight: 700, color: "#ffffff" }}>
              Multi-Objective Route Evaluation Results
            </h3>
            <span className="badge badge-emerald">
              {result.num_routes ?? routes.length} Corridors
            </span>
            <span className="badge badge-muted">
              {result.elapsed_seconds}s
            </span>
          </div>
          <p style={{ fontSize: "11px", color: "var(--text-dim)", marginTop: "2px" }}>
            Classification: <code>PRELIMINARY_CANDIDATE_CORRIDOR</code> · Region: <code>{result.region_name}</code>
          </p>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <button
            className="btn btn-primary btn-sm"
            onClick={onDownloadGeojson}
            title="Download GeoJSON FeatureCollection (RFC 7946)"
          >
            <Download size={13} />
            <span>Download GeoJSON</span>
          </button>

          <button
            className="btn btn-secondary btn-sm"
            onClick={() => setShowRawJson(!showRawJson)}
            title="Inspect raw backend JSON output"
          >
            <FileCode size={13} />
            <span>{showRawJson ? "Hide Raw JSON" : "Inspect Raw JSON"}</span>
          </button>
        </div>
      </div>

      {/* Embedded Route Comparison Matrix & 3 Route Panels */}
      <RouteComparisonTable
        result={result}
        selectedRouteId={selectedRouteId}
        onSelectRoute={onSelectRoute}
      />

      {/* Raw JSON Inspection Drawer */}
      {showRawJson && (
        <div
          style={{
            background: "var(--bg-app)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-md)",
            padding: "12px",
            maxHeight: "260px",
            overflowY: "auto",
          }}
        >
          <pre
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: "11px",
              color: "#38bdf8",
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
            }}
          >
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}

      {/* Prominent Mandatory Engineering Disclaimer */}
      <div
        style={{
          background: "rgba(15, 26, 38, 0.8)",
          border: "1px solid rgba(245, 158, 11, 0.25)",
          borderLeft: "4px solid var(--status-amber)",
          borderRadius: "var(--radius-md)",
          padding: "12px 14px",
          display: "flex",
          alignItems: "flex-start",
          gap: "10px",
        }}
      >
        <ShieldAlert size={18} color="var(--status-amber)" style={{ flexShrink: 0, marginTop: "2px" }} />
        <div style={{ fontSize: "11.5px", color: "#e2e8f0", lineHeight: "1.45" }}>
          <strong style={{ color: "#fbbf24" }}>Mandatory Engineering & Geographic Disclaimer:</strong>
          <p style={{ marginTop: "4px" }}>
            {result?.engineering_disclaimer ||
              "GeoRoute AI generates preliminary candidate corridors from available geospatial data and configurable cost assumptions. These outputs are not certified railway alignments, construction cost estimates, environmental clearances, or substitutes for professional engineering and surveying. Preliminary regional planning corridors represent bounded engineering approximations only."}
          </p>
        </div>
      </div>
    </div>
  );
}
