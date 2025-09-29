#!/usr/bin/env bash
set -euo pipefail

# Simple Bash-based model setup (no Python required)
# - Detects tier from CPU cores and RAM
# - Downloads STT/LLM/TTS artifacts for LIGHT|MEDIUM|HEAVY
# - Uses curl and unzip (install unzip if missing)
# Paths mirror models/registry.json

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
MODELS_DIR="${ROOT_DIR}/models"
ASSUME_YES=0
TIER_OVERRIDE=""

usage() {
  cat <<EOF
Usage: $0 [--tier LIGHT|MEDIUM|HEAVY] [--assume-yes]

Downloads local provider models under models/ and prints expected performance.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --assume-yes) ASSUME_YES=1 ; shift ;;
    --tier) TIER_OVERRIDE="${2:-}" ; shift 2 ;;
    -h|--help) usage ; exit 0 ;;
    *) ;;
  esac
done

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' is required" >&2; exit 1; }
}

need_cmd curl
if ! command -v unzip >/dev/null 2>&1; then
  echo "WARNING: 'unzip' not found; STT model extraction may fail. Install with: apt-get install -y unzip" >&2
fi

confirm() { # confirm "message"
  if [ "$ASSUME_YES" -eq 1 ]; then return 0; fi
  read -r -p "$1 [y/N]: " ans
  case "$ans" in
    y|Y|yes|YES) return 0;;
    *) return 1;;
  esac
}

cpu_cores() {
  if command -v nproc >/dev/null 2>&1; then nproc; else getconf _NPROCESSORS_ONLN || echo 1; fi
}

ram_gb() {
  if [ -r /proc/meminfo ]; then
    awk '/MemTotal:/ { printf "%d\n", $2/1024/1024 }' /proc/meminfo
  elif command -v sysctl >/dev/null 2>&1; then
    sysctl -n hw.memsize 2>/dev/null | awk '{ printf "%d\n", $1/1024/1024/1024 }'
  else
    echo 0
  fi
}

select_tier() {
  local cores ram
  cores=$(cpu_cores)
  ram=$(ram_gb)
  if [ -n "$TIER_OVERRIDE" ]; then echo "$TIER_OVERRIDE"; return; fi
  if [ "$ram" -ge 32 ] && [ "$cores" -ge 8 ]; then echo HEAVY; return; fi
  if [ "$ram" -ge 16 ] && [ "$cores" -ge 4 ]; then echo MEDIUM; return; fi
  echo LIGHT
}

download() { # url dest_path label
  local url="$1" dest="$2" label="$3"
  mkdir -p "$(dirname "$dest")"
  echo "Downloading $label → $dest"
  curl -L --retry 3 --fail -o "$dest" "$url"
}

extract_zip() { # zip_path target_dir
  local zip_path="$1" target_dir="$2"
  if command -v unzip >/dev/null 2>&1; then
    echo "Extracting $(basename "$zip_path") → $target_dir"
    rm -rf "$target_dir"
    mkdir -p "$target_dir"
    unzip -q -o "$zip_path" -d "$target_dir"
  else
    echo "ERROR: unzip not found. Please install unzip and re-run." >&2
    exit 1
  fi
}

setup_light() {
  # STT (Vosk small)
  local stt_zip="$MODELS_DIR/stt/vosk-model-small-en-us-0.15.zip"
  download "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip" "$stt_zip" "vosk-model-small-en-us-0.15"
  extract_zip "$stt_zip" "$MODELS_DIR/stt/vosk-model-small-en-us-0.15"
  rm -f "$stt_zip"
  # LLM (TinyLlama)
  download "https://huggingface.co/jartine/tinyllama-1.1b-chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf" \
           "$MODELS_DIR/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf" "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
  # TTS (Piper Lessac medium)
  download "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx" \
           "$MODELS_DIR/tts/en_US-lessac-medium.onnx" "en_US-lessac-medium.onnx"
  download "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json" \
           "$MODELS_DIR/tts/en_US-lessac-medium.onnx.json" "en_US-lessac-medium.onnx.json"
}

setup_medium() {
  # STT (Vosk 0.22)
  local stt_zip="$MODELS_DIR/stt/vosk-model-en-us-0.22.zip"
  download "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip" "$stt_zip" "vosk-model-en-us-0.22"
  extract_zip "$stt_zip" "$MODELS_DIR/stt/vosk-model-en-us-0.22"
  rm -f "$stt_zip"
  # LLM (Llama-2 7B)
  download "https://huggingface.co/TheBloke/Llama-2-7B-Chat-GGUF/resolve/main/llama-2-7b-chat.Q4_K_M.gguf" \
           "$MODELS_DIR/llm/llama-2-7b-chat.Q4_K_M.gguf" "llama-2-7b-chat.Q4_K_M.gguf"
  # TTS (Piper Lessac medium)
  download "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx" \
           "$MODELS_DIR/tts/en_US-lessac-medium.onnx" "en_US-lessac-medium.onnx"
  download "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json" \
           "$MODELS_DIR/tts/en_US-lessac-medium.onnx.json" "en_US-lessac-medium.onnx.json"
}

setup_heavy() {
  # STT (Vosk 0.22)
  local stt_zip="$MODELS_DIR/stt/vosk-model-en-us-0.22.zip"
  download "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip" "$stt_zip" "vosk-model-en-us-0.22"
  extract_zip "$stt_zip" "$MODELS_DIR/stt/vosk-model-en-us-0.22"
  rm -f "$stt_zip"
  # LLM (Llama-2 13B)
  download "https://huggingface.co/TheBloke/Llama-2-13B-chat-GGUF/resolve/main/llama-2-13b-chat.Q4_K_M.gguf" \
           "$MODELS_DIR/llm/llama-2-13b-chat.Q4_K_M.gguf" "llama-2-13b-chat.Q4_K_M.gguf"
  # TTS (Piper Lessac high)
  download "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/high/en_US-lessac-high.onnx" \
           "$MODELS_DIR/tts/en_US-lessac-high.onnx" "en_US-lessac-high.onnx"
  download "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/high/en_US-lessac-high.onnx.json" \
           "$MODELS_DIR/tts/en_US-lessac-high.onnx.json" "en_US-lessac-high.onnx.json"
}

main() {
  mkdir -p "$MODELS_DIR"/stt "$MODELS_DIR"/llm "$MODELS_DIR"/tts
  local tier
  tier="$(select_tier)"
  echo "=== System detection (bash) ==="
  echo "CPU cores: $(cpu_cores)"
  echo "Total RAM: $(ram_gb) GB"
  echo "Selected tier: ${tier}${TIER_OVERRIDE:+ (override)}"
  if ! confirm "Proceed with model download/setup?"; then
    echo "Aborted by user."; exit 0
  fi
  case "$tier" in
    LIGHT) setup_light ;;
    MEDIUM) setup_medium ;;
    HEAVY) setup_heavy ;;
  esac
  echo "\nModels ready under $MODELS_DIR."
}

main "$@"
