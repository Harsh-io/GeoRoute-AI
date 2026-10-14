import React, { useState, useEffect, useRef } from "react";
import TopNav from "./components/TopNav";
import PlanningPanel from "./components/PlanningPanel";
import InteractiveMap from "./components/InteractiveMap";
import MapLayersModal from "./components/MapLayersModal";
import JobProgressBanner from "./components/JobProgressBanner";
import ResultsPanel from "./components/ResultsPanel";
import CoverageAlert from "./components/CoverageAlert";
import {
  fetchHealth,
  fetchReadiness,
  fetchCapabilities,
  submitRouteJob,
  fetchJobStatus,
  fetchJobResult,
  fetchRoutesGeoJson,
  cancelJob,
  ApiError,
} from "./api/client";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

export default function App() {
  // System Diagnostics State
  const [health, setHealth] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [capabilities, setCapabilities] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(true);

  // Job & Execution State
  const [activeJob, setActiveJob] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [lastEndpoints, setLastEndpoints] = useState({
    source: { longitude: 76.9312, latitude: 31.7084, name: "Mandi Valley Entry" },
    destination: { longitude: 76.9425, latitude: 31.7220, name: "North Ridge Portal" },
  });

  // Results & GeoJSON State
  const [result, setResult] = useState(null);
  const [geojson, setGeojson] = useState(null);
  const [selectedRouteId, setSelectedRouteId] = useState(null);

  // Map Layer & Objective Visibility States
  const [visibleObjectives, setVisibleObjectives] = useState([
    "shortest_distance",
    "lowest_construction_difficulty",
    "lowest_environmental_impact",
  ]);
  const [showStudyBoundary, setShowStudyBoundary] = useState(true);
  const [isLayersModalOpen, setIsLayersModalOpen] = useState(false);
  const [isPanelCollapsed, setIsPanelCollapsed] = useState(false);

  // Error States
  const [outOfCoverageError, setOutOfCoverageError] = useState(null);
  const [generalError, setGeneralError] = useState(null);

  // Polling ref to guarantee single polling loop and clean unmount
  const pollTimerRef = useRef(null);

  // 1. Initial System Diagnostics Load
  const loadSystemStatus = async () => {
    setLoadingStatus(true);
    setGeneralError(null);
    try {
      const [h, r, c] = await Promise.all([
        fetchHealth().catch((err) => ({ status: "offline", error: err.message })),
        fetchReadiness().catch((err) => ({ status: "degraded", error: err.message })),
        fetchCapabilities().catch(() => null),
      ]);
      setHealth(h);
      setReadiness(r);
      setCapabilities(c);
    } catch (err) {
      console.error("System diagnostics error:", err);
      setGeneralError("Failed to communicate with GeoRoute AI backend service.");
    } finally {
      setLoadingStatus(false);
    }
  };

  useEffect(() => {
    loadSystemStatus();
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
      }
    };
  }, []);

  // 2. Stop Polling
  const stopPolling = () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  };

  // 3. Polling Loop
  const startPolling = (jobId) => {
    stopPolling();

    pollTimerRef.current = setInterval(async () => {
      try {
        const jobStatus = await fetchJobStatus(jobId);
        setActiveJob(jobStatus);

        const terminalStates = ["completed", "partial_success", "failed", "cancelled"];
        if (terminalStates.includes(jobStatus.status)) {
          stopPolling();

          // If successfully completed, fetch structured result & GeoJSON
          if (jobStatus.status === "completed" || jobStatus.status === "partial_success") {
            try {
              const resData = await fetchJobResult(jobId);
              setResult(resData);
              if (resData.routes && resData.routes.length > 0) {
                setSelectedRouteId(resData.routes[0].route_id);
              }
            } catch (resErr) {
              console.error("Failed to fetch job result:", resErr);
              setGeneralError(`Result retrieval error: ${resErr.message}`);
            }

            try {
              const geoData = await fetchRoutesGeoJson(jobId);
              setGeojson(geoData);
            } catch (geoErr) {
              console.warn("GeoJSON artifact fetch error:", geoErr);
            }
          }
        }
      } catch (pollErr) {
        console.error("Polling error:", pollErr);
      }
    }, 1000);
  };

  // 4. Job Submission Handler
  const handleRouteSubmit = async (payload) => {
    setSubmitting(true);
    setOutOfCoverageError(null);
    setGeneralError(null);
    setResult(null);
    setGeojson(null);
    setSelectedRouteId(null);
    setLastEndpoints({ source: payload.source, destination: payload.destination });

    try {
      const response = await submitRouteJob(payload);
      const newJob = {
        job_id: response.job_id,
        status: response.status || "queued",
        current_stage: "queued",
        elapsed_seconds: 0,
        processing_mode: payload.processing_mode,
        warnings: [],
        errors: [],
      };
      setActiveJob(newJob);
      startPolling(response.job_id);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "OUT_OF_COVERAGE" || (err.details && err.details.code === "OUT_OF_COVERAGE")) {
          setOutOfCoverageError({
            message: err.message,
            coverageNote: err.coverageNote || err.details?.coverage_note,
          });
        } else {
          setGeneralError(`${err.code}: ${err.message}`);
        }
      } else {
        setGeneralError(`Submission failed: ${err.message}`);
      }
    } finally {
      setSubmitting(false);
    }
  };

  // 5. Job Cancellation Handler
  const handleCancelJob = async (jobId) => {
    try {
      await cancelJob(jobId);
      stopPolling();
      const updatedStatus = await fetchJobStatus(jobId).catch(() => null);
      if (updatedStatus) {
        setActiveJob(updatedStatus);
      } else {
        setActiveJob((prev) => (prev ? { ...prev, status: "cancelled" } : null));
      }
    } catch (err) {
      console.error("Failed to cancel job:", err);
      setGeneralError(`Cancellation failed: ${err.message}`);
    }
  };

  // 6. Download GeoJSON Handler
  const handleDownloadGeojson = () => {
    if (!activeJob?.job_id) return;
    const downloadUrl = `/api/v1/jobs/${encodeURIComponent(activeJob.job_id)}/routes.geojson`;
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = `${activeJob.job_id}_routes.geojson`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  // 7. Objective Visibility Toggle
  const handleToggleObjective = (objKey) => {
    if (visibleObjectives.includes(objKey)) {
      if (visibleObjectives.length === 1) return; // keep at least 1 visible
      setVisibleObjectives(visibleObjectives.filter((o) => o !== objKey));
    } else {
      setVisibleObjectives([...visibleObjectives, objKey]);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>
      {/* Top Navigation */}
      <TopNav
        health={health}
        readiness={readiness}
        capabilities={capabilities}
        onRefreshStatus={loadSystemStatus}
        loadingStatus={loadingStatus}
      />

      {/* Main Workspace (Laptop-First Desktop Dashboard) */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden", position: "relative" }}>
        {/* Left-Side Planning Panel (Collapsible) */}
        {!isPanelCollapsed && (
          <PlanningPanel
            onSubmit={handleRouteSubmit}
            onCancel={handleCancelJob}
            activeJob={activeJob}
            submitting={submitting}
            backendReady={readiness?.precomputed_mode_ready}
          />
        )}

        {/* Panel Collapse / Expand Button */}
        <button
          onClick={() => setIsPanelCollapsed(!isPanelCollapsed)}
          className="btn btn-secondary btn-sm"
          title={isPanelCollapsed ? "Expand Planning Panel" : "Collapse Planning Panel"}
          style={{
            position: "absolute",
            top: "12px",
            left: isPanelCollapsed ? "12px" : "392px",
            zIndex: 35,
            padding: "5px 7px",
            background: "rgba(12, 20, 31, 0.9)",
            borderColor: "rgba(255, 255, 255, 0.15)",
          }}
        >
          {isPanelCollapsed ? <PanelLeftOpen size={14} color="var(--turquoise)" /> : <PanelLeftClose size={14} color="var(--text-muted)" />}
        </button>

        {/* Center/Right Spacious Main Workspace */}
        <main
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            overflowY: "auto",
            padding: "16px 20px",
            gap: "14px",
            background: "var(--bg-app)",
          }}
        >
          {/* Coverage Scope & Out-of-Coverage Alerts */}
          <CoverageAlert
            outOfCoverageError={outOfCoverageError}
            onDismiss={() => setOutOfCoverageError(null)}
          />

          {/* General Error Banner */}
          {generalError && (
            <div
              style={{
                background: "rgba(244, 63, 94, 0.12)",
                border: "1px solid rgba(244, 63, 94, 0.35)",
                borderRadius: "var(--radius-md)",
                padding: "10px 14px",
                color: "#fca5a5",
                fontSize: "12px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <span>{generalError}</span>
              <button
                onClick={() => setGeneralError(null)}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "#fca5a5",
                  cursor: "pointer",
                  fontSize: "14px",
                }}
              >
                ×
              </button>
            </div>
          )}

          {/* Active Job Polling & Progress Banner */}
          {activeJob && (
            <JobProgressBanner
              job={activeJob}
              onCancel={handleCancelJob}
            />
          )}

          {/* Primary Interactive Map Canvas (Laptop-First Centerpiece) */}
          <div style={{ height: "54vh", minHeight: "440px", width: "100%" }}>
            <InteractiveMap
              routesGeoJson={geojson}
              endpoints={lastEndpoints}
              selectedRouteId={selectedRouteId}
              onSelectRoute={setSelectedRouteId}
              visibleObjectives={visibleObjectives}
              onToggleObjective={handleToggleObjective}
              showStudyBoundary={showStudyBoundary}
              onToggleStudyBoundary={() => setShowStudyBoundary(!showStudyBoundary)}
              onOpenLayersModal={() => setIsLayersModalOpen(true)}
            />
          </div>

          {/* Multi-Objective Results Comparison Panel & Trade-Offs Matrix */}
          <ResultsPanel
            result={result}
            geojson={geojson}
            selectedRouteId={selectedRouteId}
            onSelectRoute={setSelectedRouteId}
            onDownloadGeojson={handleDownloadGeojson}
          />
        </main>
      </div>

      {/* Geospatial Raster & Feature Layers Inspection Modal */}
      <MapLayersModal
        isOpen={isLayersModalOpen}
        onClose={() => setIsLayersModalOpen(false)}
      />
    </div>
  );
}
