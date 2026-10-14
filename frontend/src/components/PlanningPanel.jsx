import React, { useState } from "react";
import {
  Train,
  Car,
  Zap,
  MapPin,
  Play,
  RotateCcw,
  Sliders,
  CheckSquare,
  Square,
  AlertCircle,
  XCircle,
  ShieldCheck,
} from "lucide-react";

// Curated Mandi Regional Grid Presets
const PRESETS = [
  {
    id: "mandi-standard",
    label: "Mandi Valley → North Portal (2.1 km)",
    description: "Standard corridor traverse within Mandi test grid",
    source: { longitude: 76.9312, latitude: 31.7084, name: "Mandi Valley Entry" },
    destination: { longitude: 76.9425, latitude: 31.7220, name: "North Ridge Portal" },
  },
  {
    id: "mandi-ridge",
    label: "West Portal → East Portal (3.6 km)",
    description: "Complex steep-terrain crossing with slope variations",
    source: { longitude: 76.9150, latitude: 31.6920, name: "West Valley Portal" },
    destination: { longitude: 76.9500, latitude: 31.7150, name: "East Ridge Portal" },
  },
  {
    id: "kangra-mandi-regional",
    label: "Kangra Mandir → Mandi (81 km Regional Corridor)",
    description: "Regional multi-objective routing across Himalayan terrain in Himachal Pradesh",
    source: { longitude: 76.2693, latitude: 32.0964, name: "Kangra Mandir Railway Station" },
    destination: { longitude: 76.9322, latitude: 31.7084, name: "Mandi Railway Station" },
    mode: "precomputed_regional",
    region_name: "kangra_to_mandi_corridor",
  },
  {
    id: "delhi-test",
    label: "Mandi → New Delhi (341 km Boundary Test)",
    description: "Demonstrates backend OUT_OF_COVERAGE validation in local mode",
    source: { longitude: 76.9312, latitude: 31.7084, name: "Mandi Valley Entry" },
    destination: { longitude: 77.2197, latitude: 28.6431, name: "New Delhi Railway Station" },
    mode: "precomputed",
  },
  {
    id: "mandi-delhi-regional",
    label: "Mandi → New Delhi (353 km Regional Corridor)",
    description: "Regional multi-objective routing over validated 30m regional grids",
    source: { longitude: 76.9322, latitude: 31.7084, name: "Mandi Railway Station" },
    destination: { longitude: 77.2195, latitude: 28.6430, name: "New Delhi Railway Station" },
    mode: "precomputed_regional",
    region_name: "mandi_to_delhi_corridor",
  },
];

export default function PlanningPanel({
  onSubmit,
  onCancel,
  activeJob,
  submitting,
  backendReady,
}) {
  // Form State
  const [routeType, setRouteType] = useState("railway");
  const [sourceLon, setSourceLon] = useState(76.9312);
  const [sourceLat, setSourceLat] = useState(31.7084);
  const [sourceName, setSourceName] = useState("Mandi Valley Entry");

  const [destLon, setDestLon] = useState(76.9425);
  const [destLat, setDestLat] = useState(31.7220);
  const [destName, setDestName] = useState("North Ridge Portal");

  const [processingMode, setProcessingMode] = useState("precomputed");
  const [regionName, setRegionName] = useState("mandi_corridor_study_area");
  const [objectives, setObjectives] = useState([
    "shortest_distance",
    "lowest_construction_difficulty",
    "lowest_environmental_impact",
  ]);
  const [snapToValid, setSnapToValid] = useState(true);
  const [maxSnapRadius, setMaxSnapRadius] = useState(500);
  const [backendEngine, setBackendEngine] = useState("pyorps");

  // Local Validation Error
  const [validationError, setValidationError] = useState(null);

  // Apply a Preset
  const applyPreset = (preset) => {
    setSourceLon(preset.source.longitude);
    setSourceLat(preset.source.latitude);
    setSourceName(preset.source.name);
    setDestLon(preset.destination.longitude);
    setDestLat(preset.destination.latitude);
    setDestName(preset.destination.name);
    if (preset.mode) {
      setProcessingMode(preset.mode);
    }
    if (preset.region_name) {
      setRegionName(preset.region_name);
    } else if (preset.mode === "precomputed_regional") {
      setRegionName("mandi_to_delhi_corridor");
    } else {
      setRegionName("mandi_corridor_study_area");
    }
    setValidationError(null);
  };

  // Toggle Objective
  const toggleObjective = (objKey) => {
    if (objectives.includes(objKey)) {
      if (objectives.length === 1) {
        setValidationError("At least one optimization objective must remain selected.");
        return;
      }
      setObjectives(objectives.filter((o) => o !== objKey));
    } else {
      setObjectives([...objectives, objKey]);
      setValidationError(null);
    }
  };

  // Handle Form Submission
  const handleSubmit = (e) => {
    e.preventDefault();
    setValidationError(null);

    // Basic coordinate bounds check
    const sLon = parseFloat(sourceLon);
    const sLat = parseFloat(sourceLat);
    const dLon = parseFloat(destLon);
    const dLat = parseFloat(destLat);

    if (isNaN(sLon) || isNaN(sLat) || isNaN(dLon) || isNaN(dLat)) {
      setValidationError("All coordinates must be valid floating-point numbers.");
      return;
    }

    if (sLon < -180 || sLon > 180 || dLon < -180 || dLon > 180) {
      setValidationError("Longitude must be within [-180.0, 180.0].");
      return;
    }

    if (sLat < -90 || sLat > 90 || dLat < -90 || dLat > 90) {
      setValidationError("Latitude must be within [-90.0, 90.0].");
      return;
    }

    if (sLon === dLon && sLat === dLat) {
      setValidationError("Source and destination endpoints cannot be identical.");
      return;
    }

    let finalRegion = regionName;
    if (processingMode === "precomputed_regional") {
      if (sLon < 76.65 || dLon < 76.65) {
        finalRegion = "kangra_to_mandi_corridor";
      } else {
        finalRegion = "mandi_to_delhi_corridor";
      }
    }

    const payload = {
      source: {
        longitude: sLon,
        latitude: sLat,
        name: sourceName || "Origin",
      },
      destination: {
        longitude: dLon,
        latitude: dLat,
        name: destName || "Destination",
      },
      source_crs: "EPSG:4326",
      target_crs: "EPSG:4326",
      processing_mode: processingMode,
      objectives: objectives,
      region_name: finalRegion,
      snap_to_valid: snapToValid,
      max_snap_radius_m: parseFloat(maxSnapRadius),
      backend: backendEngine,
    };

    onSubmit(payload);
  };

  const isJobRunning = activeJob && !["completed", "partial_success", "failed", "cancelled"].includes(activeJob.status);

  return (
    <aside
      style={{
        width: "380px",
        background: "var(--bg-panel)",
        borderRight: "1px solid var(--border-subtle)",
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        height: "100%",
        overflowY: "auto",
        zIndex: 10,
      }}
    >
      <form onSubmit={handleSubmit} style={{ padding: "18px 20px", display: "flex", flexDirection: "column", gap: "16px" }}>
        {/* Section 1: Route Type Selector (Extensible, Railway Active) */}
        <div>
          <div className="panel-section-title">
            <Sliders size={13} />
            <span>Infrastructure Corridor Type</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "6px" }}>
            {/* Railway Track — Active Focus */}
            <button
              type="button"
              onClick={() => setRouteType("railway")}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: "5px",
                padding: "8px 6px",
                borderRadius: "var(--radius-md)",
                background: routeType === "railway" ? "rgba(13, 148, 136, 0.25)" : "var(--bg-panel-alt)",
                border: `1px solid ${routeType === "railway" ? "var(--turquoise)" : "var(--border-subtle)"}`,
                color: routeType === "railway" ? "#ffffff" : "var(--text-muted)",
                cursor: "pointer",
                textAlign: "center",
              }}
            >
              <Train size={18} color={routeType === "railway" ? "var(--turquoise)" : "#94a3b8"} />
              <span style={{ fontSize: "11px", fontWeight: 600 }}>Railway Track</span>
              <span style={{ fontSize: "9.5px", color: "var(--turquoise)" }}>Project Focus</span>
            </button>

            {/* Road Routes — Planned */}
            <div
              title="Road routing is planned for future extension and currently disabled"
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: "5px",
                padding: "8px 6px",
                borderRadius: "var(--radius-md)",
                background: "rgba(15, 26, 38, 0.4)",
                border: "1px dashed rgba(255, 255, 255, 0.1)",
                color: "var(--text-dim)",
                cursor: "not-allowed",
                textAlign: "center",
                opacity: 0.6,
              }}
            >
              <Car size={18} color="#64748b" />
              <span style={{ fontSize: "11px", fontWeight: 500 }}>Road Routes</span>
              <span className="badge badge-muted" style={{ fontSize: "9px", padding: "1px 4px" }}>Planned</span>
            </div>

            {/* Wire/Utility Corridors — Planned */}
            <div
              title="Utility & wire corridor routing is planned for future extension and currently disabled"
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: "5px",
                padding: "8px 6px",
                borderRadius: "var(--radius-md)",
                background: "rgba(15, 26, 38, 0.4)",
                border: "1px dashed rgba(255, 255, 255, 0.1)",
                color: "var(--text-dim)",
                cursor: "not-allowed",
                textAlign: "center",
                opacity: 0.6,
              }}
            >
              <Zap size={18} color="#64748b" />
              <span style={{ fontSize: "11px", fontWeight: 500 }}>Wire / Utility</span>
              <span className="badge badge-muted" style={{ fontSize: "9px", padding: "1px 4px" }}>Planned</span>
            </div>
          </div>
        </div>

        {/* Section 2: Quick Presets */}
        <div>
          <div className="panel-section-title">
            <MapPin size={13} />
            <span>Preset Locations</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
            {PRESETS.map((p) => (
              <button
                key={p.id}
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => applyPreset(p)}
                disabled={isJobRunning}
                style={{
                  justifyContent: "flex-start",
                  textAlign: "left",
                  padding: "7px 10px",
                  fontSize: "11.5px",
                  background: "var(--bg-panel-alt)",
                }}
              >
                <div>
                  <div style={{ fontWeight: 600, color: "var(--text-main)" }}>{p.label}</div>
                  <div style={{ fontSize: "10.5px", color: "var(--text-dim)" }}>{p.description}</div>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Section 3: Coordinates Input */}
        <div>
          <div className="panel-section-title">
            <MapPin size={13} />
            <span>Endpoints (WGS84 EPSG:4326)</span>
          </div>

          {/* Source Endpoint */}
          <div
            style={{
              background: "var(--bg-panel-alt)",
              borderRadius: "var(--radius-md)",
              padding: "10px",
              marginBottom: "10px",
              border: "1px solid var(--border-subtle)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "6px" }}>
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#38bdf8" }} />
              <span style={{ fontSize: "11.5px", fontWeight: 600, color: "#38bdf8" }}>Origin (Source)</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", marginBottom: "6px" }}>
              <div>
                <label style={{ fontSize: "10.5px", color: "var(--text-dim)", display: "block" }}>Longitude (°E)</label>
                <input
                  type="number"
                  step="0.0001"
                  value={sourceLon}
                  onChange={(e) => setSourceLon(e.target.value)}
                  disabled={isJobRunning}
                  required
                />
              </div>
              <div>
                <label style={{ fontSize: "10.5px", color: "var(--text-dim)", display: "block" }}>Latitude (°N)</label>
                <input
                  type="number"
                  step="0.0001"
                  value={sourceLat}
                  onChange={(e) => setSourceLat(e.target.value)}
                  disabled={isJobRunning}
                  required
                />
              </div>
            </div>
            <input
              type="text"
              placeholder="Label (optional)"
              value={sourceName}
              onChange={(e) => setSourceName(e.target.value)}
              disabled={isJobRunning}
              style={{ fontSize: "11px", padding: "4px 8px" }}
            />
          </div>

          {/* Destination Endpoint */}
          <div
            style={{
              background: "var(--bg-panel-alt)",
              borderRadius: "var(--radius-md)",
              padding: "10px",
              border: "1px solid var(--border-subtle)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "6px" }}>
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#f43f5e" }} />
              <span style={{ fontSize: "11.5px", fontWeight: 600, color: "#f43f5e" }}>Destination (Target)</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", marginBottom: "6px" }}>
              <div>
                <label style={{ fontSize: "10.5px", color: "var(--text-dim)", display: "block" }}>Longitude (°E)</label>
                <input
                  type="number"
                  step="0.0001"
                  value={destLon}
                  onChange={(e) => setDestLon(e.target.value)}
                  disabled={isJobRunning}
                  required
                />
              </div>
              <div>
                <label style={{ fontSize: "10.5px", color: "var(--text-dim)", display: "block" }}>Latitude (°N)</label>
                <input
                  type="number"
                  step="0.0001"
                  value={destLat}
                  onChange={(e) => setDestLat(e.target.value)}
                  disabled={isJobRunning}
                  required
                />
              </div>
            </div>
            <input
              type="text"
              placeholder="Label (optional)"
              value={destName}
              onChange={(e) => setDestName(e.target.value)}
              disabled={isJobRunning}
              style={{ fontSize: "11px", padding: "4px 8px" }}
            />
          </div>
        </div>

        {/* Section 4: Multi-Objective Selection */}
        <div>
          <div className="panel-section-title">
            <Sliders size={13} />
            <span>Corridor Objectives</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
            {/* Obj 1: Shortest Distance */}
            <div
              onClick={() => !isJobRunning && toggleObjective("shortest_distance")}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "8px 10px",
                borderRadius: "var(--radius-md)",
                background: objectives.includes("shortest_distance") ? "rgba(56, 189, 248, 0.12)" : "var(--bg-panel-alt)",
                border: `1px solid ${objectives.includes("shortest_distance") ? "rgba(56, 189, 248, 0.35)" : "var(--border-subtle)"}`,
                cursor: isJobRunning ? "not-allowed" : "pointer",
              }}
            >
              {objectives.includes("shortest_distance") ? (
                <CheckSquare size={16} color="#38bdf8" />
              ) : (
                <Square size={16} color="#64748b" />
              )}
              <div style={{ flex: 1 }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#38bdf8" }}>Shortest Distance</span>
                <p style={{ fontSize: "10.5px", color: "var(--text-dim)", margin: 0 }}>
                  Minimizes geometric distance (friction = 1.0)
                </p>
              </div>
            </div>

            {/* Obj 2: Construction Difficulty */}
            <div
              onClick={() => !isJobRunning && toggleObjective("lowest_construction_difficulty")}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "8px 10px",
                borderRadius: "var(--radius-md)",
                background: objectives.includes("lowest_construction_difficulty") ? "rgba(245, 158, 11, 0.12)" : "var(--bg-panel-alt)",
                border: `1px solid ${objectives.includes("lowest_construction_difficulty") ? "rgba(245, 158, 11, 0.35)" : "var(--border-subtle)"}`,
                cursor: isJobRunning ? "not-allowed" : "pointer",
              }}
            >
              {objectives.includes("lowest_construction_difficulty") ? (
                <CheckSquare size={16} color="#f59e0b" />
              ) : (
                <Square size={16} color="#64748b" />
              )}
              <div style={{ flex: 1 }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#f59e0b" }}>Construction Difficulty</span>
                <p style={{ fontSize: "10.5px", color: "var(--text-dim)", margin: 0 }}>
                  Penalizes steep terrain slopes via Horn's formula
                </p>
              </div>
            </div>

            {/* Obj 3: Environmental Impact */}
            <div
              onClick={() => !isJobRunning && toggleObjective("lowest_environmental_impact")}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "8px 10px",
                borderRadius: "var(--radius-md)",
                background: objectives.includes("lowest_environmental_impact") ? "rgba(16, 185, 129, 0.12)" : "var(--bg-panel-alt)",
                border: `1px solid ${objectives.includes("lowest_environmental_impact") ? "rgba(16, 185, 129, 0.35)" : "var(--border-subtle)"}`,
                cursor: isJobRunning ? "not-allowed" : "pointer",
              }}
            >
              {objectives.includes("lowest_environmental_impact") ? (
                <CheckSquare size={16} color="#10b981" />
              ) : (
                <Square size={16} color="#64748b" />
              )}
              <div style={{ flex: 1 }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#10b981" }}>Environmental Impact</span>
                <p style={{ fontSize: "10.5px", color: "var(--text-dim)", margin: 0 }}>
                  Protects dense forest canopy & statutory reserves
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Section 5: Processing Mode & Snapping Settings */}
        <div style={{ background: "var(--bg-panel-alt)", padding: "10px", borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)" }}>
          <div style={{ marginBottom: "8px" }}>
            <label style={{ fontSize: "11px", fontWeight: 600, color: "var(--text-muted)", display: "block", marginBottom: "4px" }}>
              Processing Mode
            </label>
            <select
              value={processingMode}
              onChange={(e) => setProcessingMode(e.target.value)}
              disabled={isJobRunning}
            >
              <option value="precomputed">Precomputed Rasters (Fast, 10m Local Grid)</option>
              <option value="precomputed_regional">Regional Corridors (30m Mandi → Delhi Grid)</option>
              <option value="full_pipeline">Full Pipeline (Ingestion to Routing)</option>
            </select>
          </div>

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "8px" }}>
            <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "11.5px", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={snapToValid}
                onChange={(e) => setSnapToValid(e.target.checked)}
                disabled={isJobRunning}
              />
              <span>Snap blocked endpoints</span>
            </label>
            <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
              <span style={{ fontSize: "10.5px", color: "var(--text-dim)" }}>Radius:</span>
              <input
                type="number"
                min="10"
                max="5000"
                value={maxSnapRadius}
                onChange={(e) => setMaxSnapRadius(e.target.value)}
                disabled={isJobRunning || !snapToValid}
                style={{ width: "65px", padding: "3px 6px", fontSize: "11px" }}
              />
              <span style={{ fontSize: "10.5px", color: "var(--text-dim)" }}>m</span>
            </div>
          </div>
        </div>

        {/* Local Validation Error Banner */}
        {validationError && (
          <div
            style={{
              padding: "8px 10px",
              borderRadius: "var(--radius-md)",
              background: "rgba(244, 63, 94, 0.12)",
              border: "1px solid rgba(244, 63, 94, 0.3)",
              color: "#fca5a5",
              fontSize: "11.5px",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            <AlertCircle size={14} style={{ flexShrink: 0 }} />
            <span>{validationError}</span>
          </div>
        )}

        {/* Action Buttons */}
        <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: "4px" }}>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={submitting || isJobRunning}
            style={{ padding: "10px 16px", fontSize: "13px" }}
          >
            {submitting ? (
              <>
                <RotateCcw size={15} className="spin" />
                <span>Submitting Job...</span>
              </>
            ) : isJobRunning ? (
              <>
                <RotateCcw size={15} className="spin" />
                <span>Optimizing Corridor ({activeJob.status})...</span>
              </>
            ) : (
              <>
                <Play size={15} fill="#ffffff" />
                <span>Generate Candidate Corridors</span>
              </>
            )}
          </button>

          {isJobRunning && (
            <button
              type="button"
              className="btn btn-danger btn-sm"
              onClick={() => onCancel(activeJob.job_id)}
            >
              <XCircle size={14} />
              <span>Cancel Active Job ({activeJob.job_id})</span>
            </button>
          )}
        </div>
      </form>
    </aside>
  );
}
