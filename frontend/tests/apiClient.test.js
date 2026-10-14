/**
 * GeoRoute AI — Frontend API Client Unit Tests (Mocked)
 * Verifies API client error handling, HTTP status parsing, and request schemas.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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
} from "../src/api/client";

describe("GeoRoute AI - API Client (Unit Tests with Mocks)", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("1. fetchHealth() parses healthy backend status successfully", async () => {
    const mockHealth = {
      status: "healthy",
      version: "1.0.0",
      environment: "production",
      timestamp: "2026-10-14T00:00:00Z",
      uptime_seconds: 120.5,
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => mockHealth,
    });

    const data = await fetchHealth();
    expect(data.status).toBe("healthy");
    expect(data.version).toBe("1.0.0");
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/v1/health", expect.any(Object));
  });

  it("2. fetchReadiness() correctly retrieves pipeline status", async () => {
    const mockReady = {
      status: "ready",
      precomputed_mode_ready: true,
      full_pipeline_mode_ready: true,
      pyorps_engine_available: true,
      storage_ready: true,
      active_jobs: 0,
      queued_jobs: 0,
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => mockReady,
    });

    const data = await fetchReadiness();
    expect(data.status).toBe("ready");
    expect(data.pyorps_engine_available).toBe(true);
  });

  it("3. submitRouteJob() sends correct POST payload and receives job_id", async () => {
    const mockAccepted = {
      job_id: "job_test12345",
      status: "queued",
      created_at: "2026-10-14T00:00:00Z",
      status_url: "/api/v1/jobs/job_test12345",
      message: "Route generation job accepted for asynchronous processing.",
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => mockAccepted,
    });

    const payload = {
      source: { longitude: 76.9312, latitude: 31.7084, name: "Origin" },
      destination: { longitude: 76.9425, latitude: 31.722, name: "Destination" },
      source_crs: "EPSG:4326",
      target_crs: "EPSG:4326",
      processing_mode: "precomputed",
      objectives: ["shortest_distance", "lowest_construction_difficulty", "lowest_environmental_impact"],
    };

    const res = await submitRouteJob(payload);
    expect(res.job_id).toBe("job_test12345");
    expect(res.status).toBe("queued");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/generate-routes",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(payload),
      })
    );
  });

  it("4. submitRouteJob() parses OUT_OF_COVERAGE 422 error and preserves coverage_note", async () => {
    const mockErrorPayload = {
      code: "OUT_OF_COVERAGE",
      message: "Requested coordinate is outside the currently loaded Mandi study area.",
      coverage_note: "New Delhi Railway Station is 340.97km south and lies outside the precomputed grid.",
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      headers: { get: () => "application/json" },
      json: async () => ({ detail: mockErrorPayload }),
    });

    try {
      await submitRouteJob({
        source: { longitude: 76.9312, latitude: 31.7084 },
        destination: { longitude: 77.2197, latitude: 28.6431 }, // New Delhi
      });
      expect.unreachable("Should have thrown ApiError");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(422);
      expect(err.code).toBe("OUT_OF_COVERAGE");
      expect(err.coverageNote).toContain("New Delhi Railway Station is 340.97km south");
    }
  });

  it("5. fetchJobStatus() retrieves terminal job state", async () => {
    const mockStatus = {
      job_id: "job_test12345",
      status: "completed",
      current_stage: "completed",
      progress_percent: 100,
      elapsed_seconds: 0.45,
      processing_mode: "precomputed",
      warnings: [],
      errors: [],
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => mockStatus,
    });

    const status = await fetchJobStatus("job_test12345");
    expect(status.status).toBe("completed");
    expect(status.progress_percent).toBe(100);
  });

  it("6. cancelJob() successfully sends cancellation POST request", async () => {
    const mockCancel = {
      job_id: "job_test12345",
      cancelled: true,
      status: "cancelled",
      message: "Cancellation request registered.",
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => mockCancel,
    });

    const res = await cancelJob("job_test12345");
    expect(res.cancelled).toBe(true);
    expect(res.status).toBe("cancelled");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/jobs/job_test12345/cancel",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("7. Network failures throw structured NETWORK_ERROR ApiError", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error("Failed to fetch"));

    await expect(fetchHealth()).rejects.toThrowError(ApiError);
    await expect(fetchHealth()).rejects.toMatchObject({
      code: "NETWORK_ERROR",
      status: 0,
    });
  });
});
