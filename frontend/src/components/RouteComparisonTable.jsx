import React from "react";
import {
  ROUTE_COLORS,
  ROUTE_LABELS,
} from "./InteractiveMap";
import {
  TrendingUp,
  TreePine,
  ShieldCheck,
  Building2,
  Compass,
  ArrowRight,
  Info,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";

export default function RouteComparisonTable({
  result,
  selectedRouteId,
  onSelectRoute,
}) {
  if (!result || !result.routes || result.routes.length === 0) {
    return null;
  }

  const routes = result.routes;
  const source = result.source || {};
  const destination = result.destination || {};

  // Helper to format values or return "N/A"
  const fmt = (val, decimals = 1, unit = "") => {
    if (val === null || val === undefined || isNaN(val)) return "N/A";
    return `${Number(val).toFixed(decimals)}${unit ? " " + unit : ""}`;
  };

  const getForestPct = (rt) => {
    const lc = rt.landcover_distribution_percent || {};
    return lc["Tree cover / Forest"] ?? lc["forest"] ?? lc["Tree cover"] ?? lc["forest_and_tree_cover"] ?? null;
  };

  const getUrbanPct = (rt) => {
    const lc = rt.landcover_distribution_percent || {};
    return lc["Built-up / Urban"] ?? lc["builtup"] ?? lc["Urban"] ?? lc["urban_and_built_up"] ?? null;
  };

  const getCropPct = (rt) => {
    const lc = rt.landcover_distribution_percent || {};
    return lc["Cropland"] ?? lc["cropland"] ?? lc["cropland_and_alluvial_plains"] ?? null;
  };

  const getHighwayCrossings = (rt) => {
    const inf = rt.infrastructure_crossings || {};
    return inf.highway_crossings ?? inf.highway_crossings_count ?? null;
  };

  const getWaterCrossings = (rt) => {
    const inf = rt.infrastructure_crossings || {};
    return inf.water_crossings ?? inf.waterway_crossings ?? inf.waterway_crossings_count ?? null;
  };

  // Specific trade-off observations based on mathematical cost formulation
  const TRADE_OFFS = {
    shortest_distance: {
      headline: "Geometric Minimum Benchmark",
      detail:
        "Minimizes pure Euclidean length (friction = 1.0). Disregards terrain relief, cutting straight through steep Himalayan slopes and dense forest canopy.",
      badge: "Pure Distance",
    },
    lowest_construction_difficulty: {
      headline: "Gradient & Slope Minimization",
      detail:
        "Applies Horn's power-law slope penalty. Follows natural valley contours to minimize heavy earthworks, achieving a much gentler mean slope at the cost of length.",
      badge: "Gentle Gradient",
    },
    lowest_environmental_impact: {
      headline: "Forest & Reserve Avoidance",
      detail:
        "Penalizes dense canopy using Sentinel-2 NDVI weighting. Swings away from pristine forests into previously disturbed ground, sparing virgin tree cover.",
      badge: "Eco Preservation",
    },
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      {/* 1. Endpoint Snapping & Spatial Alignment Card */}
      <div
        style={{
          background: "var(--bg-panel-alt)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-md)",
          padding: "10px 14px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "10px",
          fontSize: "11.5px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <Compass size={14} color="var(--turquoise)" />
          <span>
            <strong style={{ color: "#ffffff" }}>Origin Snapping:</strong>{" "}
            {source.is_snapped ? (
              <span style={{ color: "var(--status-amber)" }}>
                Snapped ({fmt(source.snap_distance_m, 1, "m")} offset)
              </span>
            ) : (
              <span style={{ color: "var(--status-emerald)" }}>Unsnapped (Clear cell)</span>
            )}
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <Compass size={14} color="var(--turquoise)" />
          <span>
            <strong style={{ color: "#ffffff" }}>Destination Snapping:</strong>{" "}
            {destination.is_snapped ? (
              <span style={{ color: "var(--status-amber)" }}>
                Snapped ({fmt(destination.snap_distance_m, 1, "m")} offset)
              </span>
            ) : (
              <span style={{ color: "var(--status-emerald)" }}>Unsnapped (Clear cell)</span>
            )}
          </span>
        </div>

        <div style={{ color: "var(--text-dim)", fontSize: "11px" }}>
          Spatial CRS: <code>{result.spatial_reference?.crs || "EPSG:32643"}</code> · Grid: 10m
        </div>
      </div>

      {/* 2. Side-by-Side 3-Route Objective Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))", gap: "12px" }}>
        {routes.map((rt) => {
          const color = ROUTE_COLORS[rt.objective] || "#06b6d4";
          const label = ROUTE_LABELS[rt.objective] || rt.objective;
          const isSelected = selectedRouteId === rt.route_id;
          const tradeOff = TRADE_OFFS[rt.objective] || {
            headline: "Optimized Route",
            detail: "Computed by PYORPS engine.",
            badge: "Optimized",
          };

          const slope = rt.slope_profile || {};
          const forestPct = getForestPct(rt);
          const urbanPct = getUrbanPct(rt);

          return (
            <div
              key={rt.route_id}
              onClick={() => onSelectRoute(rt.route_id)}
              style={{
                background: isSelected ? "rgba(15, 34, 48, 0.95)" : "var(--bg-panel-alt)",
                border: `1.5px solid ${isSelected ? color : "var(--border-subtle)"}`,
                borderRadius: "var(--radius-md)",
                padding: "14px",
                cursor: "pointer",
                transition: "all 0.15s ease",
                boxShadow: isSelected ? `0 0 14px ${color}35` : "none",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "8px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <span style={{ width: "10px", height: "10px", borderRadius: "50%", backgroundColor: color }} />
                  <span style={{ fontWeight: 700, fontSize: "13px", color }}>
                    {label}
                  </span>
                </div>
                <span className="badge badge-muted" style={{ fontSize: "10px" }}>
                  {tradeOff.badge}
                </span>
              </div>

              {/* Core Metrics Grid */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", margin: "10px 0", fontSize: "11px" }}>
                <div>
                  <span style={{ color: "var(--text-dim)", display: "block" }}>Corridor Length</span>
                  <strong style={{ fontSize: "13.5px", color: "#ffffff" }}>
                    {fmt(rt.length_km, 2, "km")}
                  </strong>
                </div>

                <div>
                  <span style={{ color: "var(--text-dim)", display: "block" }}>Mean Slope</span>
                  <strong style={{ fontSize: "13.5px", color: slope.mean_percent > 20 ? "var(--status-amber)" : "#ffffff" }}>
                    {fmt(slope.mean_percent, 1, "%")}
                  </strong>
                </div>

                <div>
                  <span style={{ color: "var(--text-dim)", display: "block" }}>Max Slope</span>
                  <strong style={{ fontSize: "12px", color: slope.max_percent > 30 ? "var(--status-amber)" : "#ffffff" }}>
                    {fmt(slope.max_percent, 1, "%")}
                  </strong>
                </div>

                <div>
                  <span style={{ color: "var(--text-dim)", display: "block" }}>Forest Canopy</span>
                  <strong style={{ fontSize: "12px", color: forestPct !== null ? "#34d399" : "var(--text-dim)" }}>
                    {forestPct !== null ? fmt(forestPct, 1, "%") : "N/A"}
                  </strong>
                </div>
              </div>

              {/* Accumulated Cost Display */}
              <div
                style={{
                  background: "rgba(0, 0, 0, 0.25)",
                  padding: "6px 8px",
                  borderRadius: "4px",
                  fontSize: "10.5px",
                  color: "var(--text-muted)",
                  marginBottom: "10px",
                }}
              >
                <div>
                  Cost: <strong style={{ color: "#ffffff" }}>{Number(rt.accumulated_cost).toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong>
                </div>
                <div style={{ fontSize: "9.5px", color: "var(--text-dim)" }}>
                  Units: {rt.cost_units || "objective units"}
                </div>
              </div>

              {/* Trade-off summary */}
              <div style={{ fontSize: "10.5px", color: "var(--text-muted)", lineHeight: "1.4", borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: "8px" }}>
                <strong style={{ color: "var(--text-main)" }}>{tradeOff.headline}:</strong> {tradeOff.detail}
              </div>
            </div>
          );
        })}
      </div>

      {/* 3. Comprehensive Multi-Objective Comparison Table */}
      <div
        style={{
          background: "var(--bg-panel-alt)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-md)",
          overflow: "hidden",
        }}
      >
        <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontWeight: 700, fontSize: "12px", color: "var(--turquoise)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Comparative Route Metric Matrix
          </span>
          <span style={{ fontSize: "10.5px", color: "var(--text-dim)" }}>
            Sampled across 10m grid nodes
          </span>
        </div>

        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "11.5px", textAlign: "left" }}>
            <thead>
              <tr style={{ background: "rgba(0,0,0,0.2)", borderBottom: "1px solid var(--border-subtle)", color: "var(--text-dim)" }}>
                <th style={{ padding: "8px 12px" }}>Metric / Attribute</th>
                {routes.map((r) => (
                  <th key={r.route_id} style={{ padding: "8px 12px", color: ROUTE_COLORS[r.objective] || "#ffffff" }}>
                    {ROUTE_LABELS[r.objective] || r.objective}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {/* Length km */}
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <td style={{ padding: "8px 12px", fontWeight: 600 }}>Total Length (km)</td>
                {routes.map((r) => (
                  <td key={r.route_id} style={{ padding: "8px 12px", color: "#ffffff" }}>
                    {fmt(r.length_km, 2, "km")}
                  </td>
                ))}
              </tr>

              {/* Length meters */}
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <td style={{ padding: "8px 12px", color: "var(--text-dim)" }}>Total Length (meters)</td>
                {routes.map((r) => (
                  <td key={r.route_id} style={{ padding: "8px 12px" }}>
                    {fmt(r.length_m, 1, "m")}
                  </td>
                ))}
              </tr>

              {/* Accumulated Cost */}
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <td style={{ padding: "8px 12px", fontWeight: 600 }}>Accumulated Cost Value</td>
                {routes.map((r) => (
                  <td key={r.route_id} style={{ padding: "8px 12px", color: "#ffffff" }}>
                    {Number(r.accumulated_cost).toLocaleString(undefined, { maximumFractionDigits: 1 })}
                  </td>
                ))}
              </tr>

              {/* Cost Units */}
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <td style={{ padding: "8px 12px", color: "var(--text-dim)" }}>Cost Metric Units</td>
                {routes.map((r) => (
                  <td key={r.route_id} style={{ padding: "8px 12px", fontSize: "10.5px" }}>
                    <code>{r.cost_units || "dimensionless"}</code>
                  </td>
                ))}
              </tr>

              {/* Mean Slope */}
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <td style={{ padding: "8px 12px", fontWeight: 600 }}>Mean Slope Profile (%)</td>
                {routes.map((r) => (
                  <td key={r.route_id} style={{ padding: "8px 12px" }}>
                    {fmt(r.slope_profile?.mean_percent, 1, "%")}
                  </td>
                ))}
              </tr>

              {/* Max Slope */}
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <td style={{ padding: "8px 12px", fontWeight: 600 }}>Maximum Slope Encountered (%)</td>
                {routes.map((r) => (
                  <td key={r.route_id} style={{ padding: "8px 12px", color: r.slope_profile?.max_percent > 25 ? "var(--status-amber)" : "#ffffff" }}>
                    {fmt(r.slope_profile?.max_percent, 1, "%")}
                  </td>
                ))}
              </tr>

              {/* Tree Cover % */}
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <td style={{ padding: "8px 12px" }}>Forest / Tree Cover Share (%)</td>
                {routes.map((r) => {
                  const fc = getForestPct(r);
                  return (
                    <td key={r.route_id} style={{ padding: "8px 12px", color: fc !== null ? "#34d399" : "inherit" }}>
                      {fc !== null ? fmt(fc, 1, "%") : "N/A"}
                    </td>
                  );
                })}
              </tr>

              {/* Built-up % */}
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <td style={{ padding: "8px 12px" }}>Built-up / Urban Share (%)</td>
                {routes.map((r) => {
                  const uc = getUrbanPct(r);
                  return (
                    <td key={r.route_id} style={{ padding: "8px 12px" }}>
                      {uc !== null ? fmt(uc, 1, "%") : "N/A"}
                    </td>
                  );
                })}
              </tr>

              {/* Highway Crossings */}
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <td style={{ padding: "8px 12px" }}>Highway / Road Crossings</td>
                {routes.map((r) => {
                  const hc = getHighwayCrossings(r);
                  return (
                    <td key={r.route_id} style={{ padding: "8px 12px" }}>
                      {hc !== null ? hc : "N/A"}
                    </td>
                  );
                })}
              </tr>

              {/* Water Crossings */}
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <td style={{ padding: "8px 12px" }}>Water Body Crossings</td>
                {routes.map((r) => {
                  const wc = getWaterCrossings(r);
                  return (
                    <td key={r.route_id} style={{ padding: "8px 12px" }}>
                      {wc !== null ? wc : "N/A"}
                    </td>
                  );
                })}
              </tr>

              {/* Graph Nodes */}
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <td style={{ padding: "8px 12px" }}>Nodes in Path (10m Resolution)</td>
                {routes.map((r) => (
                  <td key={r.route_id} style={{ padding: "8px 12px" }}>
                    {r.num_nodes ?? r.cell_count ?? "N/A"}
                  </td>
                ))}
              </tr>

              {/* Solver Algorithm */}
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <td style={{ padding: "8px 12px" }}>Routing Engine & Algorithm</td>
                {routes.map((r) => (
                  <td key={r.route_id} style={{ padding: "8px 12px" }}>
                    <code>{r.algorithm || "pyorps_cython"}</code>
                  </td>
                ))}
              </tr>

              {/* Maturity Status */}
              <tr>
                <td style={{ padding: "8px 12px" }}>Maturity Classification</td>
                {routes.map((r) => (
                  <td key={r.route_id} style={{ padding: "8px 12px" }}>
                    <span className="badge badge-emerald" style={{ fontSize: "9.5px" }}>
                      {r.status || "preliminary_candidate_corridor"}
                    </span>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
