# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: build the React frontend
# ---------------------------------------------------------------------------
FROM node:20-slim AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Python runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# INSTALL_HEAVY=true adds torch/paddle engines (~4 GB extra).
ARG INSTALL_HEAVY=false

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

# System OCR binaries. tesseract-ocr is Apache-2.0; poppler-utils and
# ocrad/gocr are GPL and are invoked as subprocesses only.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        poppler-utils \
        mupdf-tools \
        ghostscript \
        ocrad \
        gocr \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/requirements-heavy.txt ./backend/requirements-heavy.txt
RUN if [ "$INSTALL_HEAVY" = "true" ]; then \
        pip install --no-cache-dir -r backend/requirements-heavy.txt; \
    fi

COPY backend/ ./backend/
COPY engines/ ./engines/
COPY --from=frontend /build/dist ./frontend/dist

ENV DATA_DIR=/data \
    INSTALL_HEAVY=${INSTALL_HEAVY} \
    PYTHONPATH=/app/backend

RUN mkdir -p /data/uploads /data/work

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/api/health" || exit 1

WORKDIR /app/backend

# Railway injects $PORT; fall back to 8000 for local runs.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
