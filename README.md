# Asterisk AI Voice Agent v3.0

An open-source AI Voice Agent that integrates with Asterisk/FreePBX using the Asterisk REST Interface (ARI). It features a **production-ready, two-container architecture** with **Hybrid ARI** call control, **SessionStore** state management, ExternalMedia RTP integration for reliable real-time audio capture and file-based TTS playback for robust conversation handling.

## 🌟 Features

- **Modular AI Providers**: Easily switch between cloud and local AI providers.
  - ✅ **Deepgram Voice Agent**: Fully implemented for a powerful cloud-based solution.
  - ✅ **Local AI Server**: A dedicated container that runs local models (Vosk for STT, Llama for LLM, and Piper for TTS) for full control and privacy.
- **High-Performance Architecture**: A lean `ai-engine` for call control and a separate `local-ai-server` for heavy AI processing ensures stability and scalability.
- **Hybrid ARI Architecture**: Call control using ARI with "answer caller → create mixing bridge → add caller → create ExternalMedia and add it to bridge" flow.
- **SessionStore State Management**: Centralized, typed store for all call session state, replacing legacy dictionary-based state management.
- **Real-time Communication**: ExternalMedia RTP upstream capture from Asterisk with ARI-commanded file-based playback; engine↔AI servers use WebSocket.
- **Docker-based Deployment**: Simple, two-service orchestration using Docker Compose.
- **Customizable**: Configure greetings, AI roles, and voice personalities in a simple YAML file.

## 🚀 Quick Start

### Prerequisites

- **Asterisk 16+** or **FreePBX 15+** with ARI enabled.
- **Docker** and **Docker Compose** installed.
- **Git** for cloning the repository.
- **Local AI Models** (Optional): If you want to use local AI, run the download script:
  ```bash
  ./scripts/download_models.sh
  ```

### Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/your-repo/asterisk-ai-voice-agent.git
    cd asterisk-ai-voice-agent
    ```

2.  **Configure your environment**:
    Copy the example config file `config/ai-agent.example.yaml` to `config/ai-agent.yaml` and the `.env.example` to `.env`. Edit them to match your setup, including Asterisk connection details and API keys.

3.  **Download local models (optional but recommended for the local provider)**:
    ```bash
    make model-setup
    ```
    The helper invokes `scripts/model_setup.py`, detects your hardware tier, downloads the STT/LLM/TTS bundles listed in `models/registry.json`, and skips work when everything is already cached. Light systems take ~60–90 seconds per response; heavy systems can respond in ~20 seconds.

4.  **Start the services**:
    ```bash
    docker-compose up --build -d
    ```
    This will start both the `ai-engine` and the `local-ai-server`. If you only want to use a cloud provider like Deepgram, you can start just the engine: `docker-compose up -d ai-engine`.


## ⚙️ Configuration

The system is configured via `config/ai-agent.yaml` and a `.env` file for secrets.

### Key `ai-agent.yaml` settings:
- `default_provider`: `deepgram` or `local`
- `asterisk`: Connection details for ARI.
- `providers`: Specific configurations for each AI provider.

### Required `.env` variables:
- `ASTERISK_ARI_USERNAME` & `ASTERISK_ARI_PASSWORD`
- `DEEPGRAM_API_KEY` (if using Deepgram)

## 🏗️ Project Architecture

The application is split into two Docker containers for performance and scalability:

1.  **`ai-engine`**: A lightweight service that connects to Asterisk via ARI, manages the call lifecycle, and communicates with AI providers.
2.  **`local-ai-server`**: A dedicated, powerful service that pre-loads and runs local STT, LLM, and TTS models, exposing them via a WebSocket interface.

```
┌─────────────────┐      ┌───────────┐      ┌───────────────────┐
│ Asterisk Server │◀────▶│ ai-engine │◀────▶│ AI Provider       │
│ (ARI, RTP)      │      │ (Docker)  │      │ (Deepgram, etc.)  │
└─────────────────┘      └───────────┘      └───────────────────┘
                           │     ▲
                           │ WSS │ WebSocket
                           ▼     │
                         ┌─────────────────┐
                         │ local-ai-server │
                         │ (Docker)        │
                         └─────────────────┘
```

This separation ensures that the resource-intensive AI models do not impact the real-time call handling performance of the `ai-engine`. The system uses ExternalMedia RTP for reliable audio capture and file-based TTS playback for robust conversation handling. Streaming TTS is planned as a future enhancement.

## 🧑‍💻 Development Workflow

The two-container setup enables a rapid development workflow.

-   **For `ai-engine` code changes**: `make deploy` (rebuilds image with latest code).
-   **For dependency changes**: `make deploy-full` or `make deploy-force` as needed.
-   **For rapid local testing**: `docker-compose up --build -d` keeps the containers in sync with your workspace.

Source code for the `ai-engine` is mounted as a volume, so there's no need to rebuild the image for simple Python code changes.

### Test Server

-   **Production Directory**: `/root/Asterisk-AI-Voice-Agent` (runs `main` branch)
-   **Development Directory**: `/root/Asterisk-Agent-Develop` (runs `develop` branch)
-   **Server**: Configure your own Asterisk server

## 🎯 Current Status

-   ✅ **PRODUCTION READY**: Full two-way conversation system working perfectly!
-   ✅ **Real-time Audio Processing**: ExternalMedia RTP with SSRC mapping
-   ✅ **State Management**: SessionStore-based centralized state management
-   ✅ **TTS Gating**: Perfect feedback prevention during AI responses
-   ✅ **Local AI Integration**: Vosk STT, TinyLlama LLM, Piper TTS
-   ✅ **Conversation Flow**: Complete STT → LLM → TTS pipeline working
-   ✅ **Architecture Validation**: Refactored codebase with clean separation of concerns
-   ✅ **Observability**: ConversationCoordinator drives `/health` + `/metrics` (Prometheus friendly)

**Latest Test Results (September 22, 2025):**
- **Duration**: 2 minutes
- **Conversation Exchanges**: 4 complete sentences
- **Status**: ✅ **FULLY FUNCTIONAL**

##  Roadmap

Current milestones and acceptance criteria live in [`docs/ROADMAP.md`](docs/ROADMAP.md). Update that file after each deliverable so anyone (or any AI assistant) can resume the project with a single reference.

## 🔁 Quick Regression

1. Clear logs locally (`make logs --tail=0 ai-engine`) or remotely (`make server-clear-logs`).
2. Place a short call into the AI context.
3. Verify logs for ExternalMedia bridge join, RTP frames, provider input, playback start/finish, and cleanup.
4. Run `make test-health` (or `curl $HEALTH_URL`) to confirm `active_calls: 0` within a few seconds of hangup.
5. Capture findings in `call-framework.md` or your issue tracker.

## 🔄 Switching Providers

Use the new make targets to flip between providers without touching YAML by hand:

- `make provider=<name> provider-switch` – update `config/ai-agent.yaml` locally.
- `make provider=<name> provider-reload` – update the server, restart `ai-engine`, and run `make server-health` automatically.

Example:

```bash
make provider=deepgram provider-reload
```

The command will update the server configuration, restart the container, and print the health summary so you can place a quick regression call immediately.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a pull request.

1.  Fork the repository.
2.  Create a feature branch (`git checkout -b feature/your-feature`).
3.  Commit your changes (`git commit -m 'Add some feature'`).
4.  Push to the branch (`git push origin feature/your-feature`).
5.  Open a pull request.

## 📄 License

This project is licensed under the MIT License. See the `LICENSE` file for details.
