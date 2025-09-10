#!/bin/bash

# Docker Compose Troubleshooting Script
# For Asterisk AI Voice Agent v2.0

set -e

echo "🔍 Troubleshooting Docker Compose Build Issues..."

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "❌ .env file not found. Creating from .env.example..."
    cp .env.example .env
    echo "✅ Created .env file. Please check and update API keys if needed."
fi

# Check Docker and Docker Compose
echo "🐳 Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed"
    exit 1
fi

echo "✅ Docker and Docker Compose are available"

# Check Docker daemon
echo "🔧 Checking Docker daemon..."
if ! docker info &> /dev/null; then
    echo "❌ Docker daemon is not running. Please start Docker."
    exit 1
fi

echo "✅ Docker daemon is running"

# Check for port conflicts
echo "🔌 Checking for port conflicts..."
PORTS=(6379 8000 8001 8002 8003 2223 5004)
for port in "${PORTS[@]}"; do
    if netstat -tuln | grep ":$port " &> /dev/null; then
        echo "⚠️  Port $port is already in use"
    else
        echo "✅ Port $port is available"
    fi
done

# Check available disk space
echo "💾 Checking disk space..."
DISK_USAGE=$(df / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ $DISK_USAGE -gt 80 ]; then
    echo "⚠️  Disk usage is high: ${DISK_USAGE}%"
else
    echo "✅ Disk usage is acceptable: ${DISK_USAGE}%"
fi

# Check Docker images
echo "📦 Checking Docker images..."
if docker images | grep -q "redis:7.2-alpine"; then
    echo "✅ Redis image available"
else
    echo "📥 Pulling Redis image..."
    docker pull redis:7.2-alpine
fi

if docker images | grep -q "sipwise/rtpengine"; then
    echo "✅ RTPEngine image available"
else
    echo "📥 Pulling RTPEngine image..."
    docker pull sipwise/rtpengine:latest
fi

# Check Python base image
if docker images | grep -q "python:3.11-slim"; then
    echo "✅ Python base image available"
else
    echo "📥 Pulling Python base image..."
    docker pull python:3.11-slim
fi

# Clean up any existing containers
echo "🧹 Cleaning up existing containers..."
docker-compose down --remove-orphans 2>/dev/null || true

# Remove any dangling images
echo "🧹 Removing dangling images..."
docker image prune -f

# Test building individual services
echo "🔨 Testing individual service builds..."

echo "Testing call_controller build..."
if docker build -f services/call_controller/Dockerfile -t test-call-controller .; then
    echo "✅ call_controller builds successfully"
    docker rmi test-call-controller
else
    echo "❌ call_controller build failed"
fi

echo "Testing stt_service build..."
if docker build -f services/stt_service/Dockerfile -t test-stt-service .; then
    echo "✅ stt_service builds successfully"
    docker rmi test-stt-service
else
    echo "❌ stt_service build failed"
fi

echo "Testing llm_service build..."
if docker build -f services/llm_service/Dockerfile -t test-llm-service .; then
    echo "✅ llm_service builds successfully"
    docker rmi test-llm-service
else
    echo "❌ llm_service build failed"
fi

echo "Testing tts_service build..."
if docker build -f services/tts_service/Dockerfile -t test-tts-service .; then
    echo "✅ tts_service builds successfully"
    docker rmi test-tts-service
else
    echo "❌ tts_service build failed"
fi

# Check Docker Compose configuration
echo "📋 Validating Docker Compose configuration..."
if docker-compose config > /dev/null; then
    echo "✅ Docker Compose configuration is valid"
else
    echo "❌ Docker Compose configuration has errors"
    docker-compose config
fi

echo ""
echo "🎯 Troubleshooting complete!"
echo ""
echo "If you're still having issues, try:"
echo "1. Check the specific error message from 'docker-compose up --build'"
echo "2. Try building services individually to isolate the problem"
echo "3. Check Docker logs: 'docker-compose logs [service_name]'"
echo "4. Ensure all required files are present in the project directory"
