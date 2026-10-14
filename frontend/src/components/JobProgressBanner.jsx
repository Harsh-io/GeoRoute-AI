import React from "react";
import { Loader2, CheckCircle, AlertTriangle, XCircle, Clock, ShieldAlert } from "lucide-react";

export default function JobProgressBanner({ job, onCancel }) {
  if (!job) return null;

  const isTerminal = ["completed", "partial_success", "failed", "cancelled"].includes(job.status);
  const isFailed = job.status === "failed";
  const isCancelled = job.status === "cancelled";
  const isSuccess = job.status === "completed" || job.status === "partial_success";

  // Friendly stage titles
  const STAGE_LABELS = {
    queued: "Job Queued in Thread Pool",
    validating: "Validating Endpoints against Hard Obstacles",
    downloading: "Acquiring Preprocessed Elevation & Features",
    preprocessing: "Checking Spatial Alignment & Projections",
    extracting_features: "Evaluating Slopes & Environmental Canopy",
    building_cost_surfaces: "Synthesizing 3 Independent Cost Rasters",
    routing: "Running PYORPS Cython Dijkstra Path Solver",
    validating_routes: "Verifying Gradient Limits & Engineering Curvature",
    completed: "Corridor Optimization Complete",
    partial_success: "Partial Optimization Complete",
    failed: "Optimization Pipeline Halted",
    cancelled: "Job Cancelled by Operator",
  };

  const stageTitle = STAGE_LABELS[job.status] || STAGE_LABELS[job.current_stage] || job.current_stage || job.status;

  return (
    <div
      style={{
        background: isFailed
          ? "rgba(244, 63, 94, 0.12)"
          : isSuccess
          ? "rgba(16, 185, 129, 0.1)"
          : "rgba(14, 165, 233, 0.1)",
        border: `1px solid ${
          isFailed
            ? "rgba(244, 63, 94, 0.3)"
            : isSuccess
            ? "rgba(16, 185, 129, 0.3)"
            : "rgba(14, 165, 233, 0.3)"
        }`,
        borderRadius: "var(--radius-md)",
        padding: "12px 16px",
        marginBottom: "16px",
        display: "flex",
        flexDirection: "column",
        gap: "8px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          {!isTerminal ? (
            <Loader2 size={18} className="spin" color="var(--cyan-bright)" />
          ) : isSuccess ? (
            <CheckCircle size={18} color="var(--status-emerald)" />
          ) : isCancelled ? (
            <XCircle size={18} color="var(--status-amber)" />
          ) : (
            <AlertTriangle size={18} color="var(--status-rose)" />
          )}

          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontWeight: 600, fontSize: "13px", color: "#ffffff" }}>
                {stageTitle}
              </span>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "11px",
                  padding: "1px 6px",
                  borderRadius: "4px",
                  background: "rgba(0,0,0,0.3)",
                  color: "var(--text-muted)",
                }}
              >
                {job.job_id}
              </span>
            </div>
            <p style={{ fontSize: "11.5px", color: "var(--text-muted)", margin: 0 }}>
              Mode: <code style={{ color: "var(--turquoise)" }}>{job.processing_mode}</code>
              {" · "}
              Stage: <code style={{ color: "#ffffff" }}>{job.current_stage || job.status}</code>
            </p>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "12px", color: "var(--text-muted)" }}>
            <Clock size={13} />
            <span>{job.elapsed_seconds ?? 0}s</span>
          </div>

          {!isTerminal && onCancel && (
            <button
              className="btn btn-danger btn-sm"
              onClick={() => onCancel(job.job_id)}
              style={{ padding: "3px 8px", fontSize: "11px" }}
            >
              Cancel
            </button>
          )}
        </div>
      </div>

      {/* Progress Bar (if available) */}
      {job.progress_percent !== null && job.progress_percent !== undefined && (
        <div style={{ width: "100%", background: "rgba(0,0,0,0.3)", height: "4px", borderRadius: "2px", overflow: "hidden" }}>
          <div
            style={{
              width: `${Math.min(100, Math.max(0, job.progress_percent))}%`,
              height: "100%",
              background: isSuccess
                ? "var(--status-emerald)"
                : isFailed
                ? "var(--status-rose)"
                : "var(--cyan-bright)",
              transition: "width 0.3s ease",
            }}
          />
        </div>
      )}

      {/* Warnings Stream */}
      {job.warnings && job.warnings.length > 0 && (
        <div
          style={{
            background: "rgba(245, 158, 11, 0.08)",
            border: "1px solid rgba(245, 158, 11, 0.2)",
            borderRadius: "4px",
            padding: "6px 10px",
            fontSize: "11px",
            color: "#fde68a",
          }}
        >
          <strong style={{ color: "#fbbf24" }}>Warnings:</strong> {job.warnings.join(" | ")}
        </div>
      )}

      {/* Errors Stream */}
      {job.errors && job.errors.length > 0 && (
        <div
          style={{
            background: "rgba(244, 63, 94, 0.12)",
            border: "1px solid rgba(244, 63, 94, 0.3)",
            borderRadius: "4px",
            padding: "6px 10px",
            fontSize: "11px",
            color: "#fca5a5",
          }}
        >
          <strong style={{ color: "#f87171" }}>Pipeline Errors:</strong> {job.errors.join(" | ")}
        </div>
      )}
    </div>
  );
}
