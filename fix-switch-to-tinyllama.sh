#!/bin/bash
set -e

echo "=================================================="
echo "🔧 Fixing Local Pipeline - Switch to TinyLlama"
echo "=================================================="
echo ""

cd /root/Asterisk-AI-Voice-Agent

echo "Step 1: Downloading TinyLlama model..."
echo "---------------------------------------"
mkdir -p models/llm

if [ ! -f models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf ]; then
    echo "Downloading TinyLlama (570 MB)..."
    wget -q --show-progress \
        "https://huggingface.co/jartine/tinyllama-1.1b-chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf" \
        -O models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
    echo "✅ TinyLlama downloaded"
else
    echo "✅ TinyLlama already exists"
fi

echo ""
echo "Step 2: Updating .env configuration..."
echo "---------------------------------------"

# Backup original .env
cp .env .env.backup-$(date +%Y%m%d-%H%M%S)

# Remove all LOCAL_LLM settings
sed -i '/^LOCAL_LLM_MODEL_PATH=/d' .env
sed -i '/^LOCAL_LLM_CONTEXT=/d' .env
sed -i '/^LOCAL_LLM_BATCH=/d' .env
sed -i '/^LOCAL_LLM_MAX_TOKENS=/d' .env
sed -i '/^LOCAL_LLM_TEMPERATURE=/d' .env
sed -i '/^LOCAL_LLM_INFER_TIMEOUT_SEC=/d' .env

# Add correct settings for TinyLlama
cat >> .env << 'EOF'

# TinyLlama configuration (CPU-optimized, reliable)
LOCAL_LLM_MODEL_PATH=/app/models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
LOCAL_LLM_CONTEXT=512
LOCAL_LLM_BATCH=512
LOCAL_LLM_MAX_TOKENS=24
LOCAL_LLM_TEMPERATURE=0.3
LOCAL_LLM_INFER_TIMEOUT_SEC=15
EOF

echo "✅ .env updated with TinyLlama settings"

# Show what was configured
echo ""
echo "New LLM configuration:"
grep "^LOCAL_LLM" .env | sed 's/^/  /'

echo ""
echo "Step 3: Stopping services..."
echo "---------------------------------------"
docker-compose stop local-ai-server ai-engine

echo ""
echo "Step 4: Starting local-ai-server with new model..."
echo "---------------------------------------"
docker-compose up -d local-ai-server

echo "⏳ Waiting for LLM warmup (est. 30 seconds)..."
echo ""

# Monitor logs for warmup completion
timeout=60
elapsed=0
while [ $elapsed -lt $timeout ]; do
    if docker-compose logs local-ai-server 2>&1 | grep -q "LLM STARTUP LATENCY"; then
        warmup_time=$(docker-compose logs local-ai-server 2>&1 | grep "LLM STARTUP LATENCY" | tail -1 | grep -oP '\d+\.\d+ ms')
        echo "✅ LLM warmup completed: $warmup_time"
        break
    fi
    sleep 2
    elapsed=$((elapsed + 2))
    if [ $((elapsed % 10)) -eq 0 ]; then
        echo "  ... still warming up ($elapsed seconds elapsed)"
    fi
done

if [ $elapsed -ge $timeout ]; then
    echo "⚠️  Warmup taking longer than expected, but continuing..."
fi

echo ""
echo "Step 5: Starting ai-engine..."
echo "---------------------------------------"
docker-compose up -d ai-engine

sleep 3

echo ""
echo "Step 6: Verifying configuration..."
echo "---------------------------------------"

# Check if services are running
if docker-compose ps | grep -q "local-ai-server.*Up"; then
    echo "✅ local-ai-server is running"
else
    echo "❌ local-ai-server failed to start"
    exit 1
fi

if docker-compose ps | grep -q "ai-engine.*Up"; then
    echo "✅ ai-engine is running"
else
    echo "❌ ai-engine failed to start"
    exit 1
fi

# Verify model loaded
if docker-compose logs local-ai-server 2>&1 | grep -q "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"; then
    echo "✅ TinyLlama model loaded correctly"
else
    echo "❌ TinyLlama not loaded - check logs"
    exit 1
fi

# Check configuration
llm_config=$(docker-compose logs local-ai-server 2>&1 | grep "📊 LLM Config:" | tail -1)
if echo "$llm_config" | grep -q "ctx=512.*max_tokens=24"; then
    echo "✅ LLM config correct: $(echo $llm_config | grep -oP 'ctx=\d+.*temp=[\d.]+')"
else
    echo "⚠️  LLM config may be incorrect"
fi

echo ""
echo "=================================================="
echo "✅ Migration Complete!"
echo "=================================================="
echo ""
echo "System is now using:"
echo "  • Model: TinyLlama-1.1B (570 MB)"
echo "  • Context: 512 tokens"
echo "  • Max tokens: 24"
echo "  • Timeout: 15 seconds"
echo ""
echo "Expected Performance:"
echo "  • Greeting: Immediate"
echo "  • Response time: 8-12 seconds"
echo "  • Quality: Basic but reliable"
echo ""
echo "🎯 Ready for test call!"
echo ""
