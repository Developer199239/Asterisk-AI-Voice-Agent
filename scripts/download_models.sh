#!/bin/bash
set -e

# Enhanced Model Download Script with System Spec Detection
# This script analyzes system capabilities and downloads optimized models accordingly

MODELS_DIR="models"
STT_MODELS_DIR="$MODELS_DIR/stt"
LLM_MODELS_DIR="$MODELS_DIR/llm"
TTS_MODELS_DIR="$MODELS_DIR/tts"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# System specification detection
detect_system_specs() {
    echo -e "${BLUE}=== DETECTING SYSTEM SPECIFICATIONS ===${NC}"
    
    # Detect CPU cores
    CPU_CORES=$(nproc)
    echo "CPU Cores: $CPU_CORES"
    
    # Detect total RAM in GB
    TOTAL_RAM_GB=$(free -g | awk 'NR==2{print $2}')
    echo "Total RAM: ${TOTAL_RAM_GB}GB"
    
    # Detect available disk space in GB
    AVAILABLE_DISK_GB=$(df -BG . | awk 'NR==2{print $4}' | sed 's/G//')
    echo "Available Disk: ${AVAILABLE_DISK_GB}GB"
    
    # Detect if running in Docker
    if [ -f /.dockerenv ]; then
        echo "Environment: Docker Container"
        IS_DOCKER=true
    else
        echo "Environment: Host System"
        IS_DOCKER=false
    fi
    
    # Determine system tier
    if [ $TOTAL_RAM_GB -ge 32 ] && [ $CPU_CORES -ge 8 ]; then
        SYSTEM_TIER="HEAVY"
        echo -e "${GREEN}System Tier: HEAVY (High-end system)${NC}"
    elif [ $TOTAL_RAM_GB -ge 16 ] && [ $CPU_CORES -ge 4 ]; then
        SYSTEM_TIER="MEDIUM"
        echo -e "${YELLOW}System Tier: MEDIUM (Mid-range system)${NC}"
    else
        SYSTEM_TIER="LIGHT"
        echo -e "${RED}System Tier: LIGHT (Resource-constrained system)${NC}"
    fi
    
    echo ""
}

# Model selection based on system specs - MVP Focus on uLaw 8kHz compatibility
select_models() {
    echo -e "${BLUE}=== SELECTING MVP MODELS (uLaw 8kHz Compatible) ===${NC}"
    echo "Focus: TTS and STT models optimized for uLaw 8kHz audio pipeline"
    echo ""
    
    case $SYSTEM_TIER in
        "HEAVY")
            # High-end system: Use larger, higher quality models
            echo "Selecting HEAVY tier models for optimal quality..."
            
            # STT Models (Vosk) - All Vosk models work with 8kHz input via resampling
            STT_MODEL="vosk-model-en-us-0.22"  # Larger, more accurate
            STT_URL="https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip"
            STT_SIZE="1.8GB"
            STT_SAMPLE_RATE="16000"  # Model native rate
            STT_INPUT_RATE="8000"    # AudioSocket input rate (needs resampling)
            
            # TTS Models - Focus on models that can output uLaw 8kHz
            TTS_MODEL="en_US-lessac-medium"  # High quality, can be converted to uLaw 8kHz
            TTS_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
            TTS_JSON_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
            TTS_SIZE="60MB"
            TTS_OUTPUT_RATE="22050"  # Model native rate
            TTS_TARGET_RATE="8000"   # Target rate for uLaw conversion
            ;;
            
        "MEDIUM")
            # Mid-range system: Balanced quality and performance
            echo "Selecting MEDIUM tier models for balanced performance..."
            
            # STT Models (Vosk) - Current working model
            STT_MODEL="vosk-model-small-en-us-0.15"  # Current model
            STT_URL="https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
            STT_SIZE="40MB"
            STT_SAMPLE_RATE="16000"  # Model native rate
            STT_INPUT_RATE="8000"    # AudioSocket input rate (needs resampling)
            
            # TTS Models - Current working model
            TTS_MODEL="en_US-lessac-medium"  # High quality, can be converted to uLaw 8kHz
            TTS_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
            TTS_JSON_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
            TTS_SIZE="60MB"
            TTS_OUTPUT_RATE="22050"  # Model native rate
            TTS_TARGET_RATE="8000"   # Target rate for uLaw conversion
            ;;
            
        "LIGHT")
            # Resource-constrained system: Lightweight models
            echo "Selecting LIGHT tier models for minimal resource usage..."
            
            # STT Models (Vosk) - Small model
            STT_MODEL="vosk-model-small-en-us-0.15"  # Small model
            STT_URL="https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
            STT_SIZE="40MB"
            STT_SAMPLE_RATE="16000"  # Model native rate
            STT_INPUT_RATE="8000"    # AudioSocket input rate (needs resampling)
            
            # TTS Models - Same quality, efficient
            TTS_MODEL="en_US-lessac-medium"  # High quality, can be converted to uLaw 8kHz
            TTS_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
            TTS_JSON_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
            TTS_SIZE="60MB"
            TTS_OUTPUT_RATE="22050"  # Model native rate
            TTS_TARGET_RATE="8000"   # Target rate for uLaw conversion
            ;;
    esac
    
    echo "Selected MVP Models (uLaw 8kHz Compatible):"
    echo "  STT: $STT_MODEL ($STT_SIZE)"
    echo "    - Native Rate: ${STT_SAMPLE_RATE}Hz → Input Rate: ${STT_INPUT_RATE}Hz (resampling required)"
    echo "    - Format: PCM16 → uLaw conversion via sox"
    echo "  TTS: $TTS_MODEL ($TTS_SIZE)"
    echo "    - Native Rate: ${TTS_OUTPUT_RATE}Hz → Target Rate: ${TTS_TARGET_RATE}Hz (resampling required)"
    echo "    - Format: WAV → uLaw conversion via sox"
    echo ""
    echo "Audio Pipeline: AudioSocket (8kHz) → STT (resampled to 16kHz) → TTS (resampled to 8kHz) → ARI (uLaw 8kHz)"
    echo ""
}

# Check available disk space
check_disk_space() {
    echo -e "${BLUE}=== CHECKING DISK SPACE ===${NC}"
    
    # Calculate total space needed
    case $SYSTEM_TIER in
        "HEAVY")
            TOTAL_NEEDED_GB=3
            ;;
        "MEDIUM")
            TOTAL_NEEDED_GB=1
            ;;
        "LIGHT")
            TOTAL_NEEDED_GB=0.5
            ;;
    esac
    
    if [ $AVAILABLE_DISK_GB -lt $TOTAL_NEEDED_GB ]; then
        echo -e "${RED}ERROR: Insufficient disk space!${NC}"
        echo "Available: ${AVAILABLE_DISK_GB}GB, Needed: ${TOTAL_NEEDED_GB}GB"
        exit 1
    else
        echo -e "${GREEN}Disk space check passed${NC}"
        echo "Available: ${AVAILABLE_DISK_GB}GB, Needed: ${TOTAL_NEEDED_GB}GB"
    fi
    echo ""
}

# Download function with progress
download_with_progress() {
    local url=$1
    local output=$2
    local name=$3
    
    echo "Downloading $name..."
    if command -v wget >/dev/null 2>&1; then
        wget --progress=bar:force -O "$output" "$url" 2>&1 | grep -o '[0-9]*%' | tail -1
    else
        curl -L --progress-bar -o "$output" "$url"
    fi
    echo -e "${GREEN}✓ $name downloaded successfully${NC}"
}

# Download STT model
download_stt_model() {
    echo -e "${BLUE}=== DOWNLOADING STT MODEL ===${NC}"
    
    STT_MODEL_DIR="$STT_MODELS_DIR/$STT_MODEL"
    STT_ZIP_NAME="$STT_MODEL.zip"
    
    if [ ! -d "$STT_MODEL_DIR" ]; then
        echo "Downloading $STT_MODEL ($STT_SIZE)..."
        download_with_progress "$STT_URL" "$STT_MODELS_DIR/$STT_ZIP_NAME" "$STT_MODEL"
        
        echo "Extracting $STT_MODEL..."
        unzip -q "$STT_MODELS_DIR/$STT_ZIP_NAME" -d "$STT_MODELS_DIR"
        
        echo "Cleaning up..."
        rm "$STT_MODELS_DIR/$STT_ZIP_NAME"
        
        echo -e "${GREEN}✓ STT model ready: $STT_MODEL_DIR${NC}"
    else
        echo -e "${YELLOW}STT model already exists: $STT_MODEL_DIR${NC}"
    fi
    echo ""
}

# Download LLM model
download_llm_model() {
    echo -e "${BLUE}=== DOWNLOADING LLM MODEL ===${NC}"
    
    LLM_MODEL_PATH="$LLM_MODELS_DIR/$LLM_MODEL"
    
    if [ ! -f "$LLM_MODEL_PATH" ]; then
        echo "Downloading $LLM_MODEL ($LLM_SIZE)..."
        download_with_progress "$LLM_URL" "$LLM_MODEL_PATH" "$LLM_MODEL"
        
        echo -e "${GREEN}✓ LLM model ready: $LLM_MODEL_PATH${NC}"
    else
        echo -e "${YELLOW}LLM model already exists: $LLM_MODEL_PATH${NC}"
    fi
    echo ""
}

# Download TTS model
download_tts_model() {
    echo -e "${BLUE}=== DOWNLOADING TTS MODEL ===${NC}"
    
    TTS_MODEL_PATH="$TTS_MODELS_DIR/$TTS_MODEL.onnx"
    TTS_JSON_PATH="$TTS_MODELS_DIR/$TTS_MODEL.onnx.json"
    
    if [ ! -f "$TTS_MODEL_PATH" ]; then
        echo "Downloading $TTS_MODEL ($TTS_SIZE)..."
        download_with_progress "$TTS_URL" "$TTS_MODEL_PATH" "$TTS_MODEL.onnx"
        download_with_progress "$TTS_JSON_URL" "$TTS_JSON_PATH" "$TTS_MODEL.onnx.json"
        
        echo -e "${GREEN}✓ TTS model ready: $TTS_MODEL_PATH${NC}"
    else
        echo -e "${YELLOW}TTS model already exists: $TTS_MODEL_PATH${NC}"
    fi
    echo ""
}

# Generate model configuration
generate_model_config() {
    echo -e "${BLUE}=== GENERATING MVP MODEL CONFIGURATION ===${NC}"
    
    CONFIG_FILE="model_config.json"
    
    cat > "$CONFIG_FILE" << EOF
{
    "system_tier": "$SYSTEM_TIER",
    "system_specs": {
        "cpu_cores": $CPU_CORES,
        "total_ram_gb": $TOTAL_RAM_GB,
        "available_disk_gb": $AVAILABLE_DISK_GB,
        "is_docker": $IS_DOCKER
    },
    "audio_pipeline": {
        "audiosocket_input": {
            "sample_rate": 8000,
            "format": "pcm16le",
            "channels": 1
        },
        "ari_output": {
            "sample_rate": 8000,
            "format": "ulaw",
            "channels": 1
        }
    },
    "models": {
        "stt": {
            "name": "$STT_MODEL",
            "path": "$STT_MODELS_DIR/$STT_MODEL",
            "type": "vosk",
            "native_sample_rate": $STT_SAMPLE_RATE,
            "input_sample_rate": $STT_INPUT_RATE,
            "format": "pcm16",
            "resampling_required": true,
            "resampling_ratio": 2
        },
        "tts": {
            "name": "$TTS_MODEL",
            "path": "$TTS_MODELS_DIR/$TTS_MODEL.onnx",
            "type": "piper",
            "native_sample_rate": $TTS_OUTPUT_RATE,
            "target_sample_rate": $TTS_TARGET_RATE,
            "format": "wav",
            "resampling_required": true,
            "resampling_ratio": 0.36
        }
    },
    "conversion_requirements": {
        "stt_input": "AudioSocket PCM16LE 8kHz → Vosk PCM16 16kHz (sox resample)",
        "tts_output": "Piper WAV 22kHz → ARI uLaw 8kHz (sox convert)",
        "tools_required": ["sox"]
    },
    "recommendations": {
        "max_concurrent_calls": $((TOTAL_RAM_GB / 2)),
        "audio_buffer_size": 1024,
        "stt_chunk_size": 1600,
        "tts_chunk_size": 512
    }
}
EOF
    
    echo -e "${GREEN}✓ MVP model configuration saved: $CONFIG_FILE${NC}"
    echo ""
}

# Main execution
main() {
    echo -e "${GREEN}=== ENHANCED MODEL DOWNLOAD SCRIPT ===${NC}"
    echo "This script will analyze your system and download optimized models."
    echo ""
    
    # Create models directory
    echo "Creating models directory structure..."
    mkdir -p "$STT_MODELS_DIR"
    mkdir -p "$LLM_MODELS_DIR"
    mkdir -p "$TTS_MODELS_DIR"
    
    # Detect system specifications
    detect_system_specs
    
    # Select appropriate models
    select_models
    
    # Check disk space
    check_disk_space
    
    # Download models
    download_stt_model
    download_llm_model
    download_tts_model
    
    # Generate configuration
    generate_model_config
    
    echo -e "${GREEN}=== MODEL SETUP COMPLETE ===${NC}"
    echo "System Tier: $SYSTEM_TIER"
    echo "Models downloaded and configured for optimal performance."
    echo ""
    echo "Next steps:"
    echo "1. Update your AI engine configuration to use the new models"
    echo "2. Test the system with the optimized models"
    echo "3. Monitor performance and adjust if needed"
    echo ""
}

# Run main function
main "$@"