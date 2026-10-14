/**
 * GeoRoute AI — Centralized API Client
 * Connects to the FastAPI backend service (default prefix: /api/v1).
 * Uses VITE_API_BASE_URL when defined, falling back to Vite proxy `/api/v1`.
 */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(/\/+$/, "");

/**
 * Standardized API Error class capturing error code, status, and details.
 */
export class ApiError extends Error {
  constructor(message, status, code, details = null, coverageNote = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code || `HTTP_${status}`;
    this.details = details;
    this.coverageNote = coverageNote;
  }
}

/**
 * Generic request helper with robust JSON parsing and error handling.
 */
async function request(endpoint, options = {}) {
  const url = `${API_BASE_URL}${endpoint}`;
  let res;

  try {
    res = await fetch(url, {
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        ...options.headers,
      },
      ...options,
    });
  } catch (netErr) {
    throw new ApiError(
      `Network connection failed: Unable to reach backend at ${url}. Ensure FastAPI is running on port 8000.`,
      0,
      "NETWORK_ERROR",
      { originalError: netErr.message }
    );
  }

  // Handle successful GeoJSON file download
  if (options.asBlob) {
    if (!res.ok) {
      const errText = await res.text().catch(() => "");
      throw new ApiError(
        `Failed to download artifact: ${res.statusText}`,
        res.status,
        `HTTP_${res.status}`,
        errText
      );
    }
    return await res.blob();
  }

  // Handle JSON response
  let data;
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json") || contentType.includes("application/geo+json")) {
    try {
      data = await res.json();
    } catch (parseErr) {
      throw new ApiError(
        "Malformed response from server (invalid JSON).",
        res.status,
        "PARSE_ERROR",
        { raw: parseErr.message }
      );
    }
  } else {
    data = await res.text().catch(() => "");
  }

  if (!res.ok) {
    let message = `API request failed with status ${res.status}`;
    let code = `HTTP_${res.status}`;
    let details = data;
    let coverageNote = null;

    if (data && typeof data === "object") {
      if (data.detail) {
        if (typeof data.detail === "object") {
          code = data.detail.code || code;
          message = data.detail.message || message;
          coverageNote = data.detail.coverage_note || null;
          details = data.detail;
        } else {
          message = String(data.detail);
        }
      } else if (data.message) {
        message = data.message;
        code = data.code || code;
      }
    }

    throw new ApiError(message, res.status, code, details, coverageNote);
  }

  return data;
}

// --------------------------------------------------------------------------
// System Diagnostics & Capabilities
// --------------------------------------------------------------------------

export async function fetchHealth() {
  return request("/health");
}

export async function fetchReadiness() {
  return request("/ready");
}

export async function fetchCapabilities() {
  return request("/capabilities");
}

// --------------------------------------------------------------------------
// Route Generation & Job Management
// --------------------------------------------------------------------------

/**
 * Submits a new route optimization job.
 * @param {Object} payload RouteGenerationRequest
 */
export async function submitRouteJob(payload) {
  return request("/generate-routes", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Retrieves the current status, stage, and diagnostics for a job.
 * @param {string} jobId
 */
export async function fetchJobStatus(jobId) {
  return request(`/jobs/${encodeURIComponent(jobId)}`);
}

/**
 * Retrieves the finished multi-objective route manifest and metrics.
 * @param {string} jobId
 */
export async function fetchJobResult(jobId) {
  return request(`/jobs/${encodeURIComponent(jobId)}/result`);
}

/**
 * Retrieves the WGS84 GeoJSON FeatureCollection for the job.
 * @param {string} jobId
 */
export async function fetchRoutesGeoJson(jobId) {
  return request(`/jobs/${encodeURIComponent(jobId)}/routes.geojson`);
}

/**
 * Cancels a queued or running job.
 * @param {string} jobId
 */
export async function cancelJob(jobId) {
  return request(`/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}

export { API_BASE_URL };
