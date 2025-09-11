# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Install only essential system packages for the monolithic AI engine
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

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The rest of the application is mounted via docker-compose.yml
# This allows for live code reloading during development.
# COPY src/ /app/src/
# COPY config/ /app/config/
# COPY models/ /app/models/
# COPY main.py /app/

# Command to run the application
CMD ["python3", "main.py"]