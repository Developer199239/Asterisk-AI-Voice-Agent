# --- Stage 1: "builder" ---
# This stage will compile our Python dependencies.
# We use a full Python image as it contains the necessary build tools.
FROM python:3.11 as builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    make \
    cmake \
    pkg-config \
    libffi-dev \
    libssl-dev \
    libsndfile1-dev \
    libasound2-dev \
    portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

# Set a working directory
WORKDIR /usr/src/app

# Create a virtual environment to isolate dependencies
RUN python -m venv /opt/venv

# Set the venv path for subsequent RUN commands
ENV PATH="/opt/venv/bin:$PATH"

# Copy only the requirements file to leverage Docker's layer cache.
# This is the most important optimization for developer build speed.
COPY requirements.txt .

# Install all dependencies, including build-time dependencies, into the venv.
# The --no-cache-dir flag is still a good practice.
RUN pip install --no-cache-dir -r requirements.txt


# --- Stage 2: "final" ---
# This is the final, lean image that will be deployed.
# We start from the slim base image for a small footprint.
FROM python:3.11-slim

# Install only runtime dependencies
RUN apt-get update && apt-get install -y \
    libsndfile1 \
    libasound2 \
    libportaudio2 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Set a working directory
WORKDIR /app

# Create a non-root user for security.
# This prevents the application from running with root privileges.
RUN useradd --create-home appuser
USER appuser

# Copy the compiled virtual environment from the "builder" stage.
# This is the magic step: we get all the packages without any of the build tools.
COPY --from=builder /opt/venv /opt/venv

# Copy the application source code.
# Be specific to avoid including unnecessary files like .git and to improve caching.
COPY --chown=appuser:appuser src/ ./src
COPY --chown=appuser:appuser config/ ./config
COPY --chown=appuser:appuser main.py ./

# Make the virtual environment's binaries available in the PATH.
ENV PATH="/opt/venv/bin:$PATH"

# Set the command to run the application.
# This is the same as before, but it will now run as 'appuser'.
CMD ["python", "main.py"]