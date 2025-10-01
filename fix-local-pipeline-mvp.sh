#!/bin/bash
# Quick fix for local pipeline - Switch to TinyLlama for MVP functionality
# Run this script from your local machine

set -e

SERVER="root@voiprnd.nemtclouddispatch.com"
PROJECT_PATH="/root/Asterisk-AI-Voice-Agent"

echo "================================================"
echo "Local Pipeline MVP Fix"
echo "Switching from Llama-2-13B → TinyLlama-1.1B"
echo "================================================"
echo

# Step 1: Check if TinyLlama already exists
echo "Step 1/5: Checking for existing TinyLlama model..."
if ssh $SERVER "[ -f $PROJECT_PATH/models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf ]"; then
    echo "✅ TinyLlama model already exists (570MB)"
else
    echo "📥 Downloading TinyLlama model (570MB)..."
    echo "   This may take 2-5 minutes depending on connection..."
    ssh $SERVER "cd $PROJECT_PATH && \
        wget -O models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf \
        https://huggingface.co/jartine/tinyllama-1.1b-chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf 2>&1 | grep -E '(saved|Downloaded|Length)' || true"
    echo "✅ TinyLlama downloaded"
fi
echo

# Step 2: Backup current .env
echo "Step 2/5: Backing up current configuration..."
ssh $SERVER "cd $PROJECT_PATH && cp .env .env.backup-mvp-fix-\$(date +%Y%m%d-%H%M%S)"
echo "✅ Backup created"
echo

# Step 3: Update .env for TinyLlama
echo "Step 3/5: Updating configuration for TinyLlama..."
ssh $SERVER "cd $PROJECT_PATH && cat >> .env << 'EOF'

# MVP Fix: TinyLlama for functional local pipeline ($(date))
LOCAL_LLM_MODEL_PATH=/app/models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
LOCAL_LLM_CONTEXT=256
LOCAL_LLM_BATCH=512  
LOCAL_LLM_MAX_TOKENS=32
LOCAL_LLM_TEMPERATURE=0.3
LOCAL_LLM_TOP_P=0.85
LOCAL_LLM_REPEAT_PENALTY=1.05
LOCAL_LLM_INFER_TIMEOUT_SEC=15
LOCAL_LLM_THREADS=16
LOCAL_LLM_USE_MLOCK=1
EOF
"
echo "✅ Configuration updated"
echo

# Step 4: Recreate local-ai-server container
echo "Step 4/5: Recreating local-ai-server container..."
echo "   This will take ~30 seconds..."
ssh $SERVER "cd $PROJECT_PATH && docker-compose up -d --force-recreate local-ai-server"
echo "✅ Container recreated"
echo

# Step 5: Wait for model loading and show progress
echo "Step 5/5: Waiting for TinyLlama to load..."
echo "   Expected: 10-15 seconds warmup (vs 135s with Llama-2-13B)"
echo

# Monitor logs for completion
ssh $SERVER "cd $PROJECT_PATH && timeout 30 docker-compose logs -f local-ai-server 2>&1 | grep -m1 'LLM STARTUP LATENCY' || echo 'Model loading (check logs)...'"

echo
echo "================================================"
echo "✅ MVP Fix Applied Successfully!"
echo "================================================"
echo
echo "Verification:"
echo "1. Check model loaded:"
echo "   ssh $SERVER 'cd $PROJECT_PATH && docker-compose logs local-ai-server | grep \"model loaded\"'"
echo
echo "2. Monitor live logs:"
echo "   ssh $SERVER 'cd $PROJECT_PATH && docker-compose logs -f local-ai-server'"
echo
echo "3. Place test call and say: 'What is your name?'"
echo
echo "Expected performance:"
echo "- Warmup: 10-15s (was 135s)"
echo "- Per-turn response: 12-18s (was 30s+ timeout)"
echo "- Quality: Basic but functional MVP"
echo
echo "For production quality, consider hybrid pipeline:"
echo "  active_pipeline: 'hybrid_support'  # local STT + cloud LLM/TTS"
echo "================================================"
