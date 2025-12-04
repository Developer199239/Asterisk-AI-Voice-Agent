# --- Stage 1: Builder (Dependencies) ---
# Pin to specific digest for reproducible builds and supply chain security
# python:3.11-slim as of 2025-12-04
FROM python:3.11-slim@sha256:6ed5bff4d7d377e2a72a89db63fc6e75ad92c6ee2d35e5dc8f38df2a48a9d05b as builder

WORKDIR /usr/src/app

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements first for optimal caching
COPY requirements.txt .

# Install dependencies (this layer will be cached)
RUN pip install --no-cache-dir -r requirements.txt

# --- Stage 2: Final Runtime Image ---
# Use slim image for smaller footprint
FROM python:3.11-slim@sha256:6ed5bff4d7d377e2a72a89db63fc6e75ad92c6ee2d35e5dc8f38df2a48a9d05b

# Optimization env vars
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Note: sox/curl/unzip removed - not needed at runtime
# Audio processing uses Python audioop, downloads done in install.sh

WORKDIR /app

# Create non-root user for security and grant access to asterisk group
# GID defaults to 995 (FreePBX standard) but can be overridden at build time
ARG ASTERISK_GID=995
RUN groupadd -g ${ASTERISK_GID} asterisk || true \
    && useradd --create-home appuser \
    && usermod -aG ${ASTERISK_GID} appuser

# Copy the virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application source code
COPY --chown=appuser:appuser src/ ./src
COPY --chown=appuser:appuser config/ ./config
COPY --chown=appuser:appuser main.py ./

# Prepare log directory for file logging
RUN mkdir -p /app/logs && chown appuser:appuser /app/logs

# Set PATH for virtual environment
ENV PATH="/opt/venv/bin:$PATH"

# Run the application
USER appuser
CMD ["python", "main.py"]