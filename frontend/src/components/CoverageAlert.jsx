import React from "react";
import { AlertTriangle, MapPin, Compass, Info } from "lucide-react";

export default function CoverageAlert({ outOfCoverageError, onDismiss }) {
  if (outOfCoverageError) {
    return (
      <div
        style={{
          background: "rgba(239, 68, 68, 0.12)",
          border: "1px solid rgba(239, 68, 68, 0.35)",
          borderLeft: "4px solid #ef4444",
          borderRadius: "var(--radius-md)",
          padding: "12px 16px",
          marginBottom: "14px",
          display: "flex",
          alignItems: "flex-start",
          gap: "12px",
        }}
      >
        <AlertTriangle size={20} color="#f87171" style={{ flexShrink: 0, marginTop: "2px" }} />
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h4 style={{ fontSize: "13px", fontWeight: 700, color: "#fca5a5" }}>
              OUT_OF_COVERAGE: Requested Coordinate Outside Active Study Grid
            </h4>
            {onDismiss && (
              <button
                onClick={onDismiss}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "#94a3b8",
                  cursor: "pointer",
                  fontSize: "16px",
                  padding: "0 4px",
                }}
              >
                ×
              </button>
            )}
          </div>
          <p style={{ fontSize: "12px", color: "#fecaca", marginTop: "4px", lineHeight: "1.4" }}>
            {outOfCoverageError.message}
          </p>
          {outOfCoverageError.coverageNote && (
            <div
              style={{
                marginTop: "8px",
                padding: "8px 10px",
                borderRadius: "4px",
                background: "rgba(0, 0, 0, 0.3)",
                fontSize: "11.5px",
                color: "#e2e8f0",
                lineHeight: "1.4",
              }}
            >
              <strong>Backend Coverage Notice:</strong> {outOfCoverageError.coverageNote}
            </div>
          )}
          <p style={{ fontSize: "11px", color: "#cbd5e1", marginTop: "6px", fontStyle: "italic" }}>
            Note: System policy strictly forbids artificially snapping out-of-boundary endpoints to arbitrary edge cells.
          </p>
        </div>
      </div>
    );
  }

  // Baseline Geographic Scope Indicator
  return (
    <div
      style={{
        background: "rgba(15, 34, 48, 0.7)",
        border: "1px solid rgba(20, 184, 166, 0.2)",
        borderLeft: "3px solid var(--turquoise)",
        borderRadius: "var(--radius-md)",
        padding: "9px 12px",
        marginBottom: "12px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "10px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <Compass size={15} color="var(--turquoise)" style={{ flexShrink: 0 }} />
        <span style={{ fontSize: "11.5px", color: "var(--text-muted)" }}>
          <strong style={{ color: "var(--text-main)" }}>Corridor Coverage:</strong> Mandi Local (5.8×5.7km) · Mandi–Delhi (353km) · Kangra–Mandi (81km)
        </span>
      </div>
      <span
        style={{
          fontSize: "10.5px",
          color: "var(--status-teal)",
          background: "rgba(13, 148, 136, 0.15)",
          padding: "2px 6px",
          borderRadius: "4px",
          border: "1px solid rgba(13, 148, 136, 0.3)",
        }}
      >
        Regional Grids Active
      </span>
    </div>
  );
}
