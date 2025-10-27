#!/bin/bash
# Switch OpenAI Realtime from PCM16@24kHz to g711_ulaw@8kHz
# This matches the Deepgram Voice Agent pattern (proven working)

set -e

CONFIG_FILE="/root/Asterisk-AI-Voice-Agent/config/ai-agent.yaml"

echo "🔧 Switching OpenAI Realtime to g711_ulaw (μ-law @ 8kHz)..."

# Backup current config
cp "$CONFIG_FILE" "$CONFIG_FILE.backup_$(date +%Y%m%d_%H%M%S)"

# Update provider_input_encoding
sed -i 's/provider_input_encoding: "linear16"/provider_input_encoding: "g711_ulaw"/' "$CONFIG_FILE"

# Update provider_input_sample_rate_hz
sed -i 's/provider_input_sample_rate_hz: 24000/provider_input_sample_rate_hz: 8000/' "$CONFIG_FILE"

# Update output_encoding (under openai_realtime section)
sed -i '/openai_realtime:/,/greeting:/ s/output_encoding: "linear16"/output_encoding: "g711_ulaw"/' "$CONFIG_FILE"

# Update output_sample_rate_hz (under openai_realtime section)  
sed -i '/openai_realtime:/,/greeting:/ s/output_sample_rate_hz: 24000/output_sample_rate_hz: 8000/' "$CONFIG_FILE"

echo "✅ Configuration updated!"
echo ""
echo "📋 Changed settings:"
echo "  provider_input_encoding: linear16 → g711_ulaw"
echo "  provider_input_sample_rate_hz: 24000 → 8000"
echo "  output_encoding: linear16 → g711_ulaw"
echo "  output_sample_rate_hz: 24000 → 8000"
echo ""
echo "🔄 Restart required:"
echo "  docker compose restart ai-engine"
echo ""
echo "📄 Backup saved to: $CONFIG_FILE.backup_*"
