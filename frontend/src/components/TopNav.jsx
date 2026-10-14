import React from "react";
import { Train, Cpu, Activity, RefreshCw, Layers } from "lucide-react";

export default function TopNav({ health, readiness, capabilities, onRefreshStatus, loadingStatus }) {
  const isHealthy = health?.status === "healthy";
  const isReady = readiness?.status === "ready";
  const pyorpsReady = readiness?.pyorps_engine_available;
  const pyorpsVersion = capabilities?.pyorps_version || "0.4.0";
  const activeJobs = readiness?.active_jobs ?? 0;
  const queuedJobs = readiness?.queued_jobs ?? 0;

  return (
    <header
      style={{
        height: "54px",
        background: "var(--bg-header)",
        borderBottom: "1px solid var(--border-subtle)",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 20px",
        flexShrink: 0,
        zIndex: 20,
      }}
    >
      {/* Brand & Project Identity */}
      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
        <div
          style={{
            width: "32px",
            height: "32px",
            borderRadius: "6px",
            background: "linear-gradient(135deg, #0d9488, #0891b2)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: "0 2px 8px rgba(13, 148, 136, 0.4)",
          }}
        >
          <Train size={18} color="#ffffff" />
        </div>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span
              style={{
                fontFamily: "var(--font-display)",
                fontWeight: "700",
                fontSize: "1.05rem",
                letterSpacing: "-0.01em",
                color: "#ffffff",
              }}
            >
              GeoRoute AI
            </span>
            <span
              style={{
                fontSize: "10.5px",
                padding: "1px 6px",
                borderRadius: "4px",
                background: "rgba(20, 184, 166, 0.15)",
                color: "var(--turquoise)",
                border: "1px solid rgba(20, 184, 166, 0.3)",
                fontWeight: 600,
              }}
            >
              CORRIDOR OPTIMIZER
            </span>
          </div>
          <p
            style={{
              fontSize: "11px",
              color: "var(--text-dim)",
              lineHeight: 1.1,
            }}
          >
            Terrain-Aware Multi-Objective Alignment Engine · Mandi Study Area
          </p>
        </div>
      </div>

      {/* Engineering Diagnostic Chips */}
      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
        {/* API Health Pill */}
        <div
          className={`badge ${isHealthy ? "badge-emerald" : "badge-rose"}`}
          title={health ? `Uptime: ${health.uptime_seconds}s | Version: ${health.version}` : "Backend unreachable"}
        >
          <span
            style={{
              width: "7px",
              height: "7px",
              borderRadius: "50%",
              backgroundColor: isHealthy ? "var(--status-emerald)" : "var(--status-rose)",
            }}
            className={isHealthy ? "pulse" : ""}
          />
          <span>{isHealthy ? "API v1 Healthy" : "API Offline"}</span>
        </div>

        {/* Engine Solver */}
        <div className="badge badge-cyan" title="Cython-accelerated 8-connected Dijkstra pathfinder">
          <Cpu size={12} />
          <span>PYORPS {pyorpsVersion}</span>
        </div>

        {/* Pipeline Readiness */}
        <div
          className={`badge ${isReady ? "badge-emerald" : "badge-amber"}`}
          title="Status of precomputed cost rasters and spatial alignment"
        >
          <Layers size={12} />
          <span>{readiness?.precomputed_mode_ready ? "Rasters Ready" : "Loading Rasters"}</span>
        </div>

        {/* Queue Metric */}
        <div className="badge badge-muted" title="Active and queued background optimization jobs">
          <Activity size={12} />
          <span>
            Jobs: {activeJobs} run / {queuedJobs} queue
          </span>
        </div>

        {/* Refresh Button */}
        <button
          className="btn btn-secondary btn-sm"
          onClick={onRefreshStatus}
          disabled={loadingStatus}
          title="Refresh backend status and diagnostics"
          style={{ padding: "4px 8px" }}
        >
          <RefreshCw size={13} className={loadingStatus ? "spin" : ""} />
        </button>
      </div>
    </header>
  );
}
