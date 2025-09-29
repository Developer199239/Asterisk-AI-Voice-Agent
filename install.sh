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

# --- Configuration ---
configure_env() {
    print_info "Starting interactive configuration (.env updates)..."
    ensure_env_file

    # Asterisk
    read -p "Enter your Asterisk Host [127.0.0.1]: " ASTERISK_HOST
    ASTERISK_HOST=${ASTERISK_HOST:-127.0.0.1}
    read -p "Enter your ARI Username [asterisk]: " ASTERISK_ARI_USERNAME
    ASTERISK_ARI_USERNAME=${ASTERISK_ARI_USERNAME:-asterisk}
    read -s -p "Enter your ARI Password: " ASTERISK_ARI_PASSWORD
    echo

    # API Keys (optional; set if applicable)
    read -p "Enter your OpenAI API Key (leave blank to skip): " OPENAI_API_KEY
    read -p "Enter your Deepgram API Key (leave blank to skip): " DEEPGRAM_API_KEY

    upsert_env ASTERISK_HOST "$ASTERISK_HOST"
    upsert_env ASTERISK_ARI_USERNAME "$ASTERISK_ARI_USERNAME"
    upsert_env ASTERISK_ARI_PASSWORD "$ASTERISK_ARI_PASSWORD"
    if [ -n "$OPENAI_API_KEY" ]; then upsert_env OPENAI_API_KEY "$OPENAI_API_KEY"; fi
    if [ -n "$DEEPGRAM_API_KEY" ]; then upsert_env DEEPGRAM_API_KEY "$DEEPGRAM_API_KEY"; fi

    # Clean sed backup if created
    [ -f .env.bak ] && rm -f .env.bak || true

    print_success ".env updated."
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
    case "$cfg_choice" in
        2) CFG_SRC="config/ai-agent.local.yaml"; PROFILE="local" ;;
        3) CFG_SRC="config/ai-agent.cloud-openai.yaml"; PROFILE="cloud-openai" ;;
        4) CFG_SRC="config/ai-agent.hybrid.yaml"; PROFILE="hybrid" ;;
        5) CFG_SRC="config/ai-agent.openai-agent.yaml"; PROFILE="openai-agent" ;;
        6) CFG_SRC="config/ai-agent.deepgram-agent.yaml"; PROFILE="deepgram-agent" ;;
        *) CFG_SRC="config/ai-agent.example.yaml"; PROFILE="example" ;;
    esac
    CFG_DST="config/ai-agent.yaml"
    if [ ! -f "$CFG_SRC" ]; then
        print_error "Template not found: $CFG_SRC"
        exit 1
    fi
    if [ -f "$CFG_DST" ]; then
        read -p "config/ai-agent.yaml exists. Overwrite with $CFG_SRC? [Y/n]: " ow
        if [[ ! "$ow" =~ ^[Yy]$|^$ ]]; then
            print_info "Keeping existing config/ai-agent.yaml"
            return
        fi
    fi
    cp "$CFG_SRC" "$CFG_DST"
    print_success "Wrote $CFG_DST from $CFG_SRC"

    # Offer local model setup for Local or Hybrid
    if [ "$PROFILE" = "local" ] || [ "$PROFILE" = "hybrid" ]; then
        read -p "Run local model setup now (downloads/caches models)? [Y/n]: " do_models
        if [[ "$do_models" =~ ^[Yy]$|^$ ]]; then
            if command -v make >/dev/null 2>&1; then
                make model-setup || true
            else
                python3 scripts/model_setup.py --assume-yes || true
            fi
        fi
    fi
}

start_services() {
    read -p "Build and start services now? [Y/n]: " start_service
    if [[ "$start_service" =~ ^[Yy]$|^$ ]]; then
        print_info "Building and starting services..."
        $COMPOSE up --build -d
        print_success "Services started."
        print_info "Logs:   $COMPOSE logs -f ai-engine"
        print_info "Health: curl http://127.0.0.1:15000/health"
    else
        print_info "Setup complete. Start later with: $COMPOSE up --build -d"
    fi
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
    start_services
}

main
