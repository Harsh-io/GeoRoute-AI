# GeoRoute AI — Production Backend Dockerfile
# Multi-stage image with system GDAL/PROJ dependencies and PYORPS Cython engine

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONPATH=/app/backend \
    GEOROUTE_ENV=production \
    GEOROUTE_DATA_DIR=/app/data \
    GEOROUTE_COST_DIR=/app/data/cost \
    GEOROUTE_JOBS_DIR=/app/data/jobs \
    GEOROUTE_DB_PATH=/app/data/jobs/georoute_jobs.db

# Install system C/C++ libraries and geospatial dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    libproj-dev \
    libgeos-dev \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Export GDAL include paths for native wheel compilation
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal \
    C_INCLUDE_PATH=/usr/include/gdal

WORKDIR /app

# Copy dependency configuration and install Python packages
COPY backend/pyproject.toml ./backend/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -e ./backend && \
    pip install --no-cache-dir pyorps==0.4.0

# Copy application source code and configurations
COPY backend ./backend
COPY config ./config

# Bundle precomputed Mandi local cost rasters (8.07 MB) and manifests
# Enables immediate sub-second corridor planning without external dataset downloads
COPY data/cost/rasters ./data/cost/rasters
COPY data/cost/*.json ./data/cost/

# Prepare persistent mount and runtime working directories
RUN mkdir -p /app/data/jobs /app/data/features /app/data/processed

EXPOSE 8000

# Container healthcheck targeting liveness probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/v1/health || exit 1

# Launch FastAPI application via Uvicorn factory
CMD ["sh", "-c", "uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
