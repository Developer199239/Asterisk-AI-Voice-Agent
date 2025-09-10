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
        print_error "Docker is not installed. Please install Docker and Docker Compose."
        exit 1
    fi
    if ! docker info &> /dev/null; then
        print_error "Docker daemon is not running. Please start Docker."
        exit 1
    fi
    print_success "Docker is installed and running."
}

# --- Configuration ---
configure_env() {
    print_info "Starting interactive configuration..."
    
    # AI Provider
    echo "Select an AI Provider:"
    echo "  [1] Deepgram Voice Agent (Recommended, Implemented)"
    echo "  [2] OpenAI Stack (In Development)"
    read -p "Enter your choice [1]: " ai_provider_choice
    case "$ai_provider_choice" in
        2) AI_PROVIDER="openai" ;;
        *) AI_PROVIDER="deepgram" ;;
    esac

    # API Keys
    read -p "Enter your OpenAI API Key: " OPENAI_API_KEY
    if [ "$AI_PROVIDER" == "deepgram" ]; then
        read -p "Enter your Deepgram API Key: " DEEPGRAM_API_KEY
    fi

    # Asterisk
    read -p "Enter your Asterisk Host (IP or hostname): " ASTERISK_HOST
    read -p "Enter your ARI Username [AIAgent]: " ASTERISK_ARI_USERNAME
    ASTERISK_ARI_USERNAME=${ASTERISK_ARI_USERNAME:-AIAgent}
    read -s -p "Enter your ARI Password: " ASTERISK_ARI_PASSWORD
    echo

    # Network
    read -p "Enter the external IP of this server (for RTP): " CONTAINER_HOST_IP

    # Business
    read -p "Enter your Company Name [Jugaar LLC]: " COMPANY_NAME
    COMPANY_NAME=${COMPANY_NAME:-Jugaar LLC}
    read -p "Enter the AI's Role [Customer Service Assistant]: " AI_ROLE
    AI_ROLE=${AI_ROLE:-Customer Service Assistant}
    read -p "Enter the AI's initial greeting [Hello...]: " GREETING
    GREETING=${GREETING:-"Hello, I am an AI Assistant for Jugaar LLC. How can I help you today."}

    # Create .env file
    cat > .env << EOL
# --- AI Provider ---
AI_PROVIDER=${AI_PROVIDER}
OPENAI_API_KEY=${OPENAI_API_KEY}
DEEPGRAM_API_KEY=${DEEPGRAM_API_KEY}

# --- Asterisk ---
ASTERISK_HOST=${ASTERISK_HOST}
ASTERISK_ARI_USERNAME=${ASTERISK_ARI_USERNAME}
ASTERISK_ARI_PASSWORD=${ASTERISK_ARI_PASSWORD}

# --- Network ---
CONTAINER_HOST_IP=${CONTAINER_HOST_IP}

# --- Business ---
COMPANY_NAME="${COMPANY_NAME}"
AI_ROLE="${AI_ROLE}"
GREETING="${GREETING}"

# --- Logging ---
LOG_LEVEL=INFO
EOL

    print_success "Configuration saved to .env file."
}

# --- Main ---
main() {
    echo "=========================================="
    echo " Asterisk AI Voice Agent Installation"
    echo "=========================================="
    
    check_docker
    configure_env

    read -p "Configuration is complete. Build and start the service now? [Y/n]: " start_service
    if [[ "$start_service" =~ ^[Yy]$|^$ ]]; then
        print_info "Building and starting services..."
        docker-compose up --build -d
        print_success "Services started."
        print_info "Run 'docker-compose logs -f call_controller' to see the logs."
    else
        print_info "Setup complete. You can start the services later with 'docker-compose up --build -d'."
    fi
}

main
