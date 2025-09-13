# --- Stage 1: Builder (Dependencies) ---
FROM python:3.11 as builder

WORKDIR /usr/src/app

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements first for optimal caching
COPY requirements.txt .

# Install dependencies (this layer will be cached)
RUN pip install --no-cache-dir -r requirements.txt

# --- Stage 2: Final Runtime Image ---
FROM python:3.11-slim

# Install sox for audio format conversion
RUN apt-get update && apt-get install -y sox && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create non-root user for security
RUN useradd --create-home appuser
USER appuser

# Copy the virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application source code
COPY --chown=appuser:appuser src/ ./src
COPY --chown=appuser:appuser config/ ./config
COPY --chown=appuser:appuser main.py ./

# Set PATH for virtual environment
ENV PATH="/opt/venv/bin:$PATH"

# Run the application
CMD ["python", "main.py"]