#!/bin/bash

# Asterisk AI Voice Agent - Installation Script
# This script guides the user through the initial setup and configuration process.

# --- Colors for Output ---
COLOR_RESET='\033[0m'
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[0;33m'
COLOR_RED='\033[0;31m'
COLOR_BLUE='\033[0;34m'

# --- Helper Functions ---
print_info() {
    echo -e "${COLOR_BLUE}INFO: $1${COLOR_RESET}"
}

# Determine sudo usable globally
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; else SUDO=""; fi

# --- Media path setup ---
setup_media_paths() {
    print_info "Setting up media directories and symlink for Asterisk playback..."

    # Determine sudo
    if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; else SUDO=""; fi

    # Resolve asterisk uid/gid (fall back to 995 which is common on FreePBX)
    AST_UID=$(id -u asterisk 2>/dev/null || echo 995)
    AST_GID=$(id -g asterisk 2>/dev/null || echo 995)

    # Create host media directories
    $SUDO mkdir -p /mnt/asterisk_media/ai-generated || true
    $SUDO mkdir -p /var/lib/asterisk/sounds || true

    # Ownership and permissions for fast file IO and Asterisk readability
    $SUDO chown -R "$AST_UID:$AST_GID" /mnt/asterisk_media || true
    $SUDO chmod 775 /mnt/asterisk_media /mnt/asterisk_media/ai-generated || true

    # Create/update symlink so sound:ai-generated/... resolves
    if [ -L /var/lib/asterisk/sounds/ai-generated ] || [ -e /var/lib/asterisk/sounds/ai-generated ]; then
        $SUDO rm -rf /var/lib/asterisk/sounds/ai-generated || true
    fi
    $SUDO ln -sfn /mnt/asterisk_media/ai-generated /var/lib/asterisk/sounds/ai-generated
    print_success "Linked /var/lib/asterisk/sounds/ai-generated -> /mnt/asterisk_media/ai-generated"

    # Optional tmpfs mount for performance (Linux only)
    if command -v mount >/dev/null 2>&1 && uname | grep -qi linux; then
        read -p "Mount /mnt/asterisk_media as tmpfs for low‑latency playback? [y/N]: " mount_tmpfs
        if [[ "$mount_tmpfs" =~ ^[Yy]$ ]]; then
            if ! mountpoint -q /mnt/asterisk_media 2>/dev/null; then
                $SUDO mount -t tmpfs -o size=128m,mode=0775,uid=$AST_UID,gid=$AST_GID tmpfs /mnt/asterisk_media && \
                print_success "Mounted tmpfs at /mnt/asterisk_media (128M)."
            else
                print_info "/mnt/asterisk_media is already a mountpoint; skipping tmpfs mount."
            fi
            read -p "Persist tmpfs in /etc/fstab (advanced)? [y/N]: " persist_tmpfs
            if [[ "$persist_tmpfs" =~ ^[Yy]$ ]]; then
                FSTAB_LINE="tmpfs /mnt/asterisk_media tmpfs defaults,size=128m,mode=0775,uid=$AST_UID,gid=$AST_GID 0 0"
                if ! grep -q "/mnt/asterisk_media" /etc/fstab 2>/dev/null; then
                    echo "$FSTAB_LINE" | $SUDO tee -a /etc/fstab >/dev/null && print_success "Added tmpfs entry to /etc/fstab."
                else
                    print_info "/etc/fstab already contains an entry for /mnt/asterisk_media; skipping."
                fi
            fi
        fi
    fi

    # Quick verification
    if [ -d /var/lib/asterisk/sounds/ai-generated ]; then
        print_success "Media path ready: /var/lib/asterisk/sounds/ai-generated -> /mnt/asterisk_media/ai-generated"
    else
        print_warning "Media path symlink missing; please ensure permissions and rerun setup."
    fi
}

print_success() {
    echo -e "${COLOR_GREEN}SUCCESS: $1${COLOR_RESET}"
}

print_warning() {
    echo -e "${COLOR_YELLOW}WARNING: $1${COLOR_RESET}"
}

print_error() {
    echo -e "${COLOR_RED}ERROR: $1${COLOR_RESET}"
}

# --- System Checks ---
check_docker() {
    print_info "Checking for Docker..."
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker."
        exit 1
    fi
    if ! docker info &> /dev/null; then
        print_error "Docker daemon is not running. Please start Docker."
        exit 1
    fi
    print_success "Docker is installed and running."
}

choose_compose_cmd() {
    if command -v docker-compose >/dev/null 2>&1; then
        COMPOSE="docker-compose"
    elif docker compose version >/dev/null 2>&1; then
        COMPOSE="docker compose"
    else
        print_error "Neither 'docker-compose' nor 'docker compose' is available. Please install Docker Compose."
        exit 1
    fi
    print_info "Using Compose command: $COMPOSE"
}

check_asterisk_modules() {
    if ! command -v asterisk >/dev/null 2>&1; then
        print_warning "Asterisk CLI not found. Skipping Asterisk module checks."
        return
    fi
    print_info "Checking Asterisk modules (res_ari_applications, app_audiosocket)..."
    asterisk -rx "module show like res_ari_applications" || true
    asterisk -rx "module show like app_audiosocket" || true
    print_info "If modules are not Running, on FreePBX use: asterisk-switch-version (select 18+)."
}

# --- Env file helpers ---
ensure_env_file() {
    if [ ! -f .env ]; then
        if [ -f .env.example ]; then
            cp .env.example .env
            print_success "Created .env from .env.example"
        else
            print_error ".env.example not found. Cannot create .env"
            exit 1
        fi
    else
        print_info ".env already exists; values will be updated in-place."
    fi
}

upsert_env() {
    local KEY="$1"; shift
    local VAL="$1"; shift
    # Replace existing (even if commented) or append
    if grep -qE "^[# ]*${KEY}=" .env; then
        sed -i.bak -E "s|^[# ]*${KEY}=.*|${KEY}=${VAL}|" .env
    else
        echo "${KEY}=${VAL}" >> .env
    fi
}

# Ensure yq exists on Ubuntu/CentOS, otherwise try to install a static binary; fallback will be used if all fail.
ensure_yq() {
    if command -v yq >/dev/null 2>&1; then
        return 0
    fi
    print_info "yq not found; attempting installation..."
    if command -v apt-get >/dev/null 2>&1; then
        $SUDO apt-get update && $SUDO apt-get install -y yq || true
    elif command -v yum >/dev/null 2>&1; then
        $SUDO yum -y install epel-release || true
        $SUDO yum -y install yq || true
    elif command -v dnf >/dev/null 2>&1; then
        $SUDO dnf -y install yq || true
    elif command -v snap >/dev/null 2>&1; then
        $SUDO snap install yq || true
    fi
    if command -v yq >/dev/null 2>&1; then
        print_success "yq installed."
        return 0
    fi
    # Download static binary as last resort (detect OS/ARCH)
    print_info "Falling back to installing yq static binary..."
    ARCH=$(uname -m)
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    case "${OS}-${ARCH}" in
        linux-x86_64|linux-amd64) YQ_BIN="yq_linux_amd64" ;;
        linux-aarch64|linux-arm64) YQ_BIN="yq_linux_arm64" ;;
        darwin-x86_64|darwin-amd64) YQ_BIN="yq_darwin_amd64" ;;
        darwin-arm64) YQ_BIN="yq_darwin_arm64" ;;
        *) YQ_BIN="yq_linux_amd64" ;;
    esac
    TMP_YQ="/tmp/${YQ_BIN}"
    if command -v curl >/dev/null 2>&1; then
        curl -L "https://github.com/mikefarah/yq/releases/latest/download/${YQ_BIN}" -o "$TMP_YQ" || true
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$TMP_YQ" "https://github.com/mikefarah/yq/releases/latest/download/${YQ_BIN}" || true
    fi
    if [ -f "$TMP_YQ" ]; then
        $SUDO mv "$TMP_YQ" /usr/local/bin/yq && $SUDO chmod +x /usr/local/bin/yq || true
    fi
    if command -v yq >/dev/null 2>&1; then
        print_success "yq installed (static)."
        return 0
    fi
    print_warning "yq could not be installed; will use sed/awk fallback."
    return 1
}

# Update config/ai-agent.yaml llm block with GREETING and AI_ROLE.
update_yaml_llm() {
    local CFG_DST="config/ai-agent.yaml"
    if [ ! -f "$CFG_DST" ]; then
        print_warning "YAML not found at $CFG_DST; skipping llm update."
        return 0
    fi
    if command -v yq >/dev/null 2>&1; then
        # Use env() in yq to avoid quoting issues
        GREETING="${GREETING}"
        AI_ROLE="${AI_ROLE}"
        export GREETING AI_ROLE
        if yq -i '.llm.initial_greeting = env(GREETING) | .llm.prompt = env(AI_ROLE) | (.llm.model //= "gpt-4o")' "$CFG_DST"; then
            print_success "Updated llm.* in $CFG_DST via yq."
            return 0
        else
            print_warning "yq update failed; falling back to append llm block."
        fi
    fi
    # Fallback: append an llm block at end (last key wins in PyYAML)
    local G_ESC
    local R_ESC
    G_ESC=$(printf '%s' "$GREETING" | sed 's/"/\\"/g')
    R_ESC=$(printf '%s' "$AI_ROLE" | sed 's/"/\\"/g')
    cat >> "$CFG_DST" <<EOF

# llm block inserted by install.sh (fallback path)
llm:
  initial_greeting: "$G_ESC"
  prompt: "$R_ESC"
  model: "gpt-4o"
EOF
    print_success "Appended llm block to $CFG_DST (fallback)."
}

# --- Local model helpers ---
autodetect_local_models() {
    print_info "Auto-detecting local model artifacts under ./models to set .env paths..."
    local stt="" llm="" tts=""

    local has_gpu=0
    if command -v nvidia-smi >/dev/null 2>&1; then
        if nvidia-smi -L >/dev/null 2>&1; then
            has_gpu=1
        fi
    elif command -v rocm-smi >/dev/null 2>&1; then
        if rocm-smi -i >/dev/null 2>&1; then
            has_gpu=1
        fi
    fi
    # STT preference: 0.22 > small 0.15
    if [ -d models/stt/vosk-model-en-us-0.22 ]; then
        stt="/app/models/stt/vosk-model-en-us-0.22"
    elif [ -d models/stt/vosk-model-small-en-us-0.15 ]; then
        stt="/app/models/stt/vosk-model-small-en-us-0.15"
    fi
    # LLM preference: favor smaller GGUFs on CPU-only hosts for responsiveness
    if [ "$has_gpu" -eq 1 ]; then
        if [ -f models/llm/llama-2-13b-chat.Q4_K_M.gguf ]; then
            llm="/app/models/llm/llama-2-13b-chat.Q4_K_M.gguf"
        elif [ -f models/llm/llama-2-7b-chat.Q4_K_M.gguf ]; then
            llm="/app/models/llm/llama-2-7b-chat.Q4_K_M.gguf"
        elif [ -f models/llm/phi-3-mini-4k-instruct.Q4_K_M.gguf ]; then
            llm="/app/models/llm/phi-3-mini-4k-instruct.Q4_K_M.gguf"
        elif [ -f models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf ]; then
            llm="/app/models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
        fi
    else
        # Prefer TinyLlama first on CPU-only systems for best responsiveness.
        if [ -f models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf ]; then
            llm="/app/models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
        elif [ -f models/llm/phi-3-mini-4k-instruct.Q4_K_M.gguf ]; then
            llm="/app/models/llm/phi-3-mini-4k-instruct.Q4_K_M.gguf"
        elif [ -f models/llm/llama-2-7b-chat.Q4_K_M.gguf ]; then
            llm="/app/models/llm/llama-2-7b-chat.Q4_K_M.gguf"
        elif [ -f models/llm/llama-2-13b-chat.Q4_K_M.gguf ]; then
            llm="/app/models/llm/llama-2-13b-chat.Q4_K_M.gguf"
        fi
    fi
    # TTS preference: high > medium
    if [ -f models/tts/en_US-lessac-high.onnx ]; then
        tts="/app/models/tts/en_US-lessac-high.onnx"
    elif [ -f models/tts/en_US-lessac-medium.onnx ]; then
        tts="/app/models/tts/en_US-lessac-medium.onnx"
    fi

    if [ -n "$stt" ]; then upsert_env LOCAL_STT_MODEL_PATH "$stt"; fi
    if [ -n "$llm" ]; then upsert_env LOCAL_LLM_MODEL_PATH "$llm"; fi
    if [ -n "$tts" ]; then upsert_env LOCAL_TTS_MODEL_PATH "$tts"; fi

    # Set performance parameters based on detected tier
    set_performance_params_for_llm "$llm"

    # Clean sed backup if created
    [ -f .env.bak ] && rm -f .env.bak || true
    print_success "Local model paths and performance tuning updated in .env (if detected)."
}

set_performance_params_for_llm() {
    local llm_path="$1"
    
    # Skip if no LLM detected
    [ -z "$llm_path" ] && return 0
    
    # Determine tier based on model name
    local tier="LIGHT_CPU"
    if echo "$llm_path" | grep -q "tinyllama"; then
        tier="LIGHT_CPU"
    elif echo "$llm_path" | grep -q "phi-3-mini"; then
        tier="MEDIUM_CPU"
    elif echo "$llm_path" | grep -q "llama-2-7b"; then
        tier="HEAVY_CPU"
    elif echo "$llm_path" | grep -q "llama-2-13b"; then
        tier="HEAVY_GPU"
    fi
    
    print_info "Setting performance parameters for tier: $tier"
    
    # Set tier-appropriate parameters
    case "$tier" in
        LIGHT_CPU)
            upsert_env LOCAL_LLM_CONTEXT "512"
            upsert_env LOCAL_LLM_BATCH "512"
            upsert_env LOCAL_LLM_MAX_TOKENS "24"
            upsert_env LOCAL_LLM_TEMPERATURE "0.3"
            upsert_env LOCAL_LLM_INFER_TIMEOUT_SEC "45"
            print_info "  → Context: 512, Max tokens: 24, Timeout: 45s (conservative for older CPUs)"
            ;;
        MEDIUM_CPU)
            upsert_env LOCAL_LLM_CONTEXT "512"
            upsert_env LOCAL_LLM_BATCH "512"
            upsert_env LOCAL_LLM_MAX_TOKENS "32"
            upsert_env LOCAL_LLM_TEMPERATURE "0.3"
            upsert_env LOCAL_LLM_INFER_TIMEOUT_SEC "30"
            print_info "  → Context: 512, Max tokens: 32, Timeout: 30s (optimized for Phi-3-mini)"
            ;;
        HEAVY_CPU)
            # Conservative settings - use Phi-3 params even for HEAVY_CPU
            # Llama-2-7B often too slow without modern CPU features (AVX-512)
            upsert_env LOCAL_LLM_CONTEXT "512"
            upsert_env LOCAL_LLM_BATCH "512"
            upsert_env LOCAL_LLM_MAX_TOKENS "28"
            upsert_env LOCAL_LLM_TEMPERATURE "0.3"
            upsert_env LOCAL_LLM_INFER_TIMEOUT_SEC "35"
            print_info "  → Context: 512, Max tokens: 28, Timeout: 35s (conservative for reliability)"
            ;;
        HEAVY_GPU)
            upsert_env LOCAL_LLM_CONTEXT "1024"
            upsert_env LOCAL_LLM_BATCH "512"
            upsert_env LOCAL_LLM_MAX_TOKENS "48"
            upsert_env LOCAL_LLM_TEMPERATURE "0.3"
            upsert_env LOCAL_LLM_INFER_TIMEOUT_SEC "20"
            print_info "  → Context: 1024, Max tokens: 48, Timeout: 20s (optimized for GPU acceleration)"
            ;;
    esac
}

wait_for_local_ai_health() {
    print_info "Waiting for local-ai-server to become healthy (port 8765)..."
    # Ensure service started (build if needed)
    $COMPOSE up -d --build local-ai-server
    # Up to ~20 minutes (120 * 10s)
    for i in $(seq 1 120); do
        status=$(docker inspect -f '{{.State.Health.Status}}' local_ai_server 2>/dev/null || echo "starting")
        if [ "$status" = "healthy" ]; then
            print_success "local-ai-server is healthy."
            return 0
        fi
        if (( i % 6 == 0 )); then
            print_info "Still waiting for local models to load (elapsed ~$((i/6*1)) min). This can take 15–20 minutes on first start..."
        fi
        sleep 10
    done
    print_warning "local-ai-server did not report healthy within ~20 minutes; continuing. Use: $COMPOSE logs -f local-ai-server to monitor."
    return 1
}

# --- Configuration ---
configure_env() {
    print_info "Starting interactive configuration (.env updates)..."
    ensure_env_file

    # Prefill from existing .env if present
    local ASTERISK_HOST_DEFAULT="" ASTERISK_ARI_USERNAME_DEFAULT="" ASTERISK_ARI_PASSWORD_DEFAULT=""
    local OPENAI_API_KEY_DEFAULT="" DEEPGRAM_API_KEY_DEFAULT=""
    if [ -f .env ]; then
        ASTERISK_HOST_DEFAULT=$(grep -E '^[# ]*ASTERISK_HOST=' .env | tail -n1 | sed -E 's/^[# ]*ASTERISK_HOST=//')
        ASTERISK_ARI_USERNAME_DEFAULT=$(grep -E '^[# ]*ASTERISK_ARI_USERNAME=' .env | tail -n1 | sed -E 's/^[# ]*ASTERISK_ARI_USERNAME=//')
        ASTERISK_ARI_PASSWORD_DEFAULT=$(grep -E '^[# ]*ASTERISK_ARI_PASSWORD=' .env | tail -n1 | sed -E 's/^[# ]*ASTERISK_ARI_PASSWORD=//')
        OPENAI_API_KEY_DEFAULT=$(grep -E '^[# ]*OPENAI_API_KEY=' .env | tail -n1 | sed -E 's/^[# ]*OPENAI_API_KEY=//')
        DEEPGRAM_API_KEY_DEFAULT=$(grep -E '^[# ]*DEEPGRAM_API_KEY=' .env | tail -n1 | sed -E 's/^[# ]*DEEPGRAM_API_KEY=//')
    fi

    # Asterisk (blank keeps existing)
    read -p "Enter your Asterisk Host [${ASTERISK_HOST_DEFAULT:-127.0.0.1}]: " ASTERISK_HOST_INPUT
    ASTERISK_HOST=${ASTERISK_HOST_INPUT:-${ASTERISK_HOST_DEFAULT:-127.0.0.1}}
    read -p "Enter your ARI Username [${ASTERISK_ARI_USERNAME_DEFAULT:-asterisk}]: " ASTERISK_ARI_USERNAME_INPUT
    ASTERISK_ARI_USERNAME=${ASTERISK_ARI_USERNAME_INPUT:-${ASTERISK_ARI_USERNAME_DEFAULT:-asterisk}}
    read -s -p "Enter your ARI Password [unchanged if blank]: " ASTERISK_ARI_PASSWORD_INPUT
    echo
    if [ -n "$ASTERISK_ARI_PASSWORD_INPUT" ]; then
        ASTERISK_ARI_PASSWORD="$ASTERISK_ARI_PASSWORD_INPUT"
    else
        ASTERISK_ARI_PASSWORD="$ASTERISK_ARI_PASSWORD_DEFAULT"
    fi

    # API Keys (optional; blank keeps existing)
    read -p "Enter your OpenAI API Key (leave blank to keep existing): " OPENAI_API_KEY_INPUT
    read -p "Enter your Deepgram API Key (leave blank to keep existing): " DEEPGRAM_API_KEY_INPUT

    upsert_env ASTERISK_HOST "$ASTERISK_HOST"
    upsert_env ASTERISK_ARI_USERNAME "$ASTERISK_ARI_USERNAME"
    upsert_env ASTERISK_ARI_PASSWORD "$ASTERISK_ARI_PASSWORD"
    if [ -n "$OPENAI_API_KEY_INPUT" ]; then upsert_env OPENAI_API_KEY "$OPENAI_API_KEY_INPUT"; fi
    if [ -n "$DEEPGRAM_API_KEY_INPUT" ]; then upsert_env DEEPGRAM_API_KEY "$DEEPGRAM_API_KEY_INPUT"; fi

    # Greeting and AI Role prompts (idempotent; prefill from .env if present)
    local GREETING_DEFAULT AI_ROLE_DEFAULT
    if [ -f .env ]; then
        GREETING_DEFAULT=$(grep -E '^[# ]*GREETING=' .env | tail -n1 | sed -E 's/^[# ]*GREETING=//' | sed -E 's/^"(.*)"$/\1/')
        AI_ROLE_DEFAULT=$(grep -E '^[# ]*AI_ROLE=' .env | tail -n1 | sed -E 's/^[# ]*AI_ROLE=//' | sed -E 's/^"(.*)"$/\1/')
    fi
    [ -z "$GREETING_DEFAULT" ] && GREETING_DEFAULT="Hello, how can I help you today?"
    [ -z "$AI_ROLE_DEFAULT" ] && AI_ROLE_DEFAULT="You are a concise and helpful voice assistant. Keep replies under 20 words unless asked for detail."

    read -p "Enter initial Greeting [${GREETING_DEFAULT}]: " GREETING
    GREETING=${GREETING:-$GREETING_DEFAULT}
    read -p "Enter AI Role/Persona [${AI_ROLE_DEFAULT}]: " AI_ROLE
    AI_ROLE=${AI_ROLE:-$AI_ROLE_DEFAULT}

    # Escape quotes for .env
    local G_ESC R_ESC
    G_ESC=$(printf '%s' "$GREETING" | sed 's/"/\\"/g')
    R_ESC=$(printf '%s' "$AI_ROLE" | sed 's/"/\\"/g')
    upsert_env GREETING "\"$G_ESC\""
    upsert_env AI_ROLE "\"$R_ESC\""

    # Clean sed backup if created
    [ -f .env.bak ] && rm -f .env.bak || true

    print_success ".env updated."
    print_info "If you don't have API keys now, you can add them later to .env and then recreate containers: 'docker-compose up -d' (use '--build' if images changed). Note: simple 'restart' will not pick up new .env values."
}

select_config_template() {
    echo "Select a configuration template for config/ai-agent.yaml:"
    echo "  [1] General example (pipelines + monolithic fallback)"
    echo "  [2] Local-only pipeline"
    echo "  [3] Cloud-only OpenAI pipeline"
    echo "  [4] Hybrid (Local STT + OpenAI LLM + Deepgram TTS)"
    echo "  [5] Monolithic OpenAI Realtime agent"
    echo "  [6] Monolithic Deepgram Voice Agent"
    read -p "Enter your choice [1]: " cfg_choice
    # Always start from the canonical pipelines template, then set active/defaults
    CFG_SRC="config/ai-agent.example.yaml"
    PROFILE="example"
    PIPELINE_CHOICE=""
    case "$cfg_choice" in
        2) PROFILE="local"; PIPELINE_CHOICE="local_only" ;;
        3) PROFILE="cloud-openai"; PIPELINE_CHOICE="cloud_openai" ;;
        4) PROFILE="hybrid"; PIPELINE_CHOICE="hybrid_deepgram_openai" ;;
        5) PROFILE="openai-agent" ;;
        6) PROFILE="deepgram-agent" ;;
        *) PROFILE="example"; PIPELINE_CHOICE="cloud_openai" ;;
    esac
    CFG_DST="config/ai-agent.yaml"
    if [ ! -f "$CFG_SRC" ]; then
        print_error "Template not found: $CFG_SRC"
        exit 1
    fi
    if [ -f "$CFG_DST" ]; then
        print_info "Overwriting existing config/ai-agent.yaml with $CFG_SRC"
    fi
    cp "$CFG_SRC" "$CFG_DST"
    print_success "Wrote $CFG_DST from $CFG_SRC"

    # Set active_pipeline or default_provider based on selection
    if [ -n "$PIPELINE_CHOICE" ]; then
        if command -v yq >/dev/null 2>&1; then
            yq -i ".active_pipeline = \"$PIPELINE_CHOICE\"" "$CFG_DST" || true
        else
            # sed fallback
            if grep -qE '^[# ]*active_pipeline:' "$CFG_DST"; then
                sed -i.bak -E "s|^([# ]*active_pipeline: ).*|\1$PIPELINE_CHOICE|" "$CFG_DST" || true
            else
                echo "active_pipeline: $PIPELINE_CHOICE" >> "$CFG_DST"
            fi
        fi
    else
        # Monolithic choices: adjust default_provider accordingly
        case "$PROFILE" in
            openai-agent)
                if command -v yq >/dev/null 2>&1; then
                    yq -i '.default_provider = "openai_realtime"' "$CFG_DST" || true
                else
                    sed -i.bak -E 's|^([# ]*default_provider: ).*|\1"openai_realtime"|' "$CFG_DST" || true
                fi
                ;;
            deepgram-agent)
                if command -v yq >/dev/null 2>&1; then
                    yq -i '.default_provider = "deepgram"' "$CFG_DST" || true
                else
                    sed -i.bak -E 's|^([# ]*default_provider: ).*|\1"deepgram"|' "$CFG_DST" || true
                fi
                ;;
        esac
    fi

    # Ensure yq is available and update llm.* from the values captured earlier
    ensure_yq || true
    update_yaml_llm || true

    # Offer local model setup for Local or Hybrid
    if [ "$PROFILE" = "local" ] || [ "$PROFILE" = "hybrid" ]; then
        read -p "Run local model setup now (downloads/caches models)? [Y/n]: " do_models
        if [[ "$do_models" =~ ^[Yy]$|^$ ]]; then
            if command -v make >/dev/null 2>&1; then
                make model-setup || true
            else
                if command -v python3 >/dev/null 2>&1; then
                    print_info "Running model setup with host python3..."
                    python3 scripts/model_setup.py --assume-yes || true
                else
                    print_info "Host python3 not found; running one-off container for model setup."
                    $COMPOSE run --rm ai-engine python /app/scripts/model_setup.py --assume-yes || true
                fi
            fi
        fi
        # Note: LLM/STT/TTS settings are configured in YAML; .env is not mutated for models.
    fi
}

start_services() {
    read -p "Build and start services now? [Y/n]: " start_service
    if [[ "$start_service" =~ ^[Yy]$|^$ ]]; then
        if [ "$PROFILE" = "local" ] || [ "$PROFILE" = "hybrid" ]; then
            print_info "Starting local-ai-server first..."
            print_info "Note: first startup of local models may take 15–20 minutes depending on CPU/RAM/disk. Monitor: $COMPOSE logs -f local-ai-server"
            wait_for_local_ai_health
            print_info "Starting ai-engine..."
            $COMPOSE up -d --build ai-engine
        else
            print_info "Building and starting ai-engine only (no local models required)..."
            $COMPOSE up --build -d ai-engine
        fi
        print_success "Services started."
        print_info "Logs:   $COMPOSE logs -f ai-engine"
        print_info "Health: curl http://127.0.0.1:15000/health"
    else
        print_info "Setup complete. Start later with: $COMPOSE up --build -d"
    fi

    # Always print recommended Asterisk dialplan snippet to test the chosen pipeline/provider
    print_asterisk_dialplan_snippet
}

# --- Output recommended Asterisk dialplan for the chosen profile ---
print_asterisk_dialplan_snippet() {
    echo
    echo "=========================================="
    echo " Asterisk Dialplan Snippet (copy/paste)"
    echo "=========================================="

    APP_NAME="asterisk-ai-voice-agent"
    PIPELINE_NAME=""
    PROVIDER_OVERRIDE=""

    case "$PROFILE" in
        local)
            PIPELINE_NAME="local_only"
            ;;
        hybrid)
            PIPELINE_NAME="hybrid_deepgram_openai"
            ;;
        cloud-openai)
            PIPELINE_NAME="cloud_openai"
            ;;
        openai-agent)
            PROVIDER_OVERRIDE="openai"
            ;;
        deepgram-agent)
            PROVIDER_OVERRIDE="deepgram"
            ;;
        *)
            # Example template defaults to cloud_openai pipeline
            PIPELINE_NAME="cloud_openai"
            ;;
    esac

    echo "Add this to your extensions_custom.conf (or via FreePBX Config Edit):"
    echo
    if [ -n "$PROVIDER_OVERRIDE" ]; then
        cat <<EOF
[from-ai-agent-test]
exten => s,1,NoOp(Test AI engine with provider override: $PROVIDER_OVERRIDE)
 same => n,Set(AI_PROVIDER=$PROVIDER_OVERRIDE)
 same => n,Stasis($APP_NAME)
 same => n,Hangup()
EOF
    else
        cat <<EOF
[from-ai-agent-test]
exten => s,1,NoOp(Test AI engine with pipeline: $PIPELINE_NAME)
 same => n,Set(AI_PROVIDER=$PIPELINE_NAME)
 same => n,Stasis($APP_NAME)
 same => n,Hangup()
EOF
    fi

    cat <<'EOF'

; Optional: AudioSocket helper context for media transport (telephony μ-law 8kHz)
[from-ai-agent-audiosocket]
exten => _X.,1,NoOp(Local channel starting AudioSocket for ${EXTEN})
 same => n,Answer()
 same => n,Set(AUDIOSOCKET_HOST=127.0.0.1)
 same => n,Set(AUDIOSOCKET_PORT=8090)
 same => n,Set(AUDIOSOCKET_UUID=${EXTEN})
 same => n,AudioSocket(${AUDIOSOCKET_UUID},${AUDIOSOCKET_HOST}:${AUDIOSOCKET_PORT},ulaw)
 same => n,Hangup()

; Keepalive leg for ;1 while engine streams audio (optional)
exten => s,1,NoOp(Local keepalive for AudioSocket leg)
 same => n,Wait(60)
 same => n,Hangup()
EOF

    echo
    echo "Next steps:"
    echo " - Create a FreePBX Custom Destination to from-ai-agent-test,s,1 and route a test call to it."
    echo " - Ensure modules are loaded: asterisk -rx 'module show like res_ari_applications' and 'module show like app_audiosocket'"
    echo " - Watch logs: $COMPOSE logs -f ai-engine | sed -n '1,200p'"
}

# --- Main ---
main() {
    echo "=========================================="
    echo " Asterisk AI Voice Agent Installation"
    echo "=========================================="
    
    check_docker
    choose_compose_cmd
    check_asterisk_modules
    configure_env
    select_config_template
    setup_media_paths
    start_services
}

main
