# Asterisk AI Voice Agent v3.0

An open-source AI Voice Agent that integrates with Asterisk/FreePBX using the Asterisk REST Interface (ARI). It features a **two-container, Hybrid ARI architecture** with **AudioSocket-first streaming capture**, **SessionStore** state management, and automatic fallback to tmpfs-based file playback for robust conversation handling.

## 🌟 Features

- **Modular AI Providers**: Easily switch between cloud and local AI providers.
  - ✅ **Deepgram Voice Agent**: Fully implemented for a powerful cloud-based solution.
  - ✅ **Local AI Server**: A dedicated container that runs local models (Vosk for STT, Llama for LLM, and Piper for TTS) for full control and privacy.
- **High-Performance Architecture**: A lean `ai-engine` for call control and a separate `local-ai-server` for heavy AI processing ensures stability and scalability.
- **Hybrid ARI Architecture**: Call control uses the AudioSocket-first Hybrid ARI flow (answer caller → create bridge → originate AudioSocket leg) with ExternalMedia kept only as a fallback.
- **Streaming Transport Defaults**: `StreamingPlaybackManager` paces provider audio in 20 ms frames with configurable jitter buffering, start delay, and graceful fallback to file playback (`config/ai-agent.yaml` → `streaming.*`).
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
    This brings up both the `ai-engine` and the `local-ai-server`. If you’re running cloud-only (Deepgram or OpenAI Realtime), you may start just the engine: `docker-compose up -d ai-engine`. After the containers settle, confirm the AudioSocket listener in the logs (`AudioSocket server listening on 0.0.0.0:8090`).


## ⚙️ Configuration

The system is configured via `config/ai-agent.yaml` and a `.env` file for secrets.

### Key `ai-agent.yaml` settings:
- `default_provider`: `deepgram` or `local`
- `asterisk`: Connection details for ARI.
- `providers`: Specific configurations for each AI provider.

### Required `.env` variables:
- `ASTERISK_ARI_USERNAME` & `ASTERISK_ARI_PASSWORD`
- `DEEPGRAM_API_KEY` (if using Deepgram)

### Optional local AI tuning (set via environment variables)
- `LOCAL_LLM_MODEL_PATH`: absolute path to an alternative GGUF file mounted into the container.
- `LOCAL_LLM_MAX_TOKENS`: cap the number of response tokens (default `48` for faster replies).
- `LOCAL_LLM_TEMPERATURE`, `LOCAL_LLM_TOP_P`, `LOCAL_LLM_REPEAT_PENALTY`: sampling controls for the TinyLlama runtime.
- `LOCAL_LLM_THREADS`, `LOCAL_LLM_CONTEXT`, `LOCAL_LLM_BATCH`: advanced performance knobs; defaults auto-detect CPU cores and favour latency.
- `LOCAL_STT_MODEL_PATH`, `LOCAL_TTS_MODEL_PATH`: override default Vosk/Piper models if you preload alternates under `models/`.

## 🏗️ Project Architecture

The application is split into two Docker containers for performance and scalability:

1.  **`ai-engine`**: A lightweight service that connects to Asterisk via ARI, manages the call lifecycle, hosts the AudioSocket TCP listener, and communicates with AI providers.
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

This separation ensures that the resource-intensive AI models do not impact the real-time call handling performance of the `ai-engine`. The system now prefers AudioSocket streaming for upstream capture, falls back to file playback when buffer depth drops, and keeps ExternalMedia RTP as a safety path.

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

## 🎯 GA Progress Snapshot

**Completed (Milestones 1–6)**
- SessionStore-only state management and ConversationCoordinator metrics.
- AudioSocket-first streaming transport with configurable pacing (`streaming.*`) and post-TTS guard rails.
- Deepgram AudioSocket regression passing end-to-end with adaptive buffering.
- OpenAI Realtime provider parity, μ-law alignment, and keepalive fixes.

**In Flight for GA (Milestones 7–8)**
- YAML-defined pipelines with hot reload (`docs/milestones/milestone-7-configurable-pipelines.md`).
- Optional monitoring stack (`docs/milestones/milestone-8-monitoring-stack.md`) and dashboards.

**Launch Tasks (per open-source strategy)**
- Finalize contributor assets (CONTRIBUTING, issue templates, GitHub Discussions/Discord setup).
- Publish tuning guide, FreePBX integration updates, and GA release notes.
- Prepare community launch collateral (blog/video/announcement copy) before tagging GA.

Track detailed acceptance criteria in [`docs/ROADMAP.md`](docs/ROADMAP.md) and the launch checklist in `plan/Asterisk AI Voice Agent_ Your Comprehensive Open Source Launch Strategy.md`.

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
