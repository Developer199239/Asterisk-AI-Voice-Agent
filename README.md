# Asterisk AI Voice Agent v3.0

An open-source AI Voice Agent that integrates with Asterisk/FreePBX using the Asterisk REST Interface (ARI). It features a **production-ready, two-container architecture** with **Hybrid ARI** call control, **SessionStore** state management, ExternalMedia RTP integration for reliable real-time audio capture and file-based TTS playback for robust conversation handling.

## 🌟 Why Asterisk AI Voice Agent?

This project is designed to be the most powerful, flexible, and easy-to-use open-source AI voice agent for Asterisk. Here’s what makes it different:

*   **Asterisk-Native:** No external telephony providers required. It works directly with your existing Asterisk/FreePBX installation.
*   **Truly Open Source:** The entire project is open source (MIT licensed), so you have complete transparency and control.
*   **Hybrid AI:** Seamlessly switch between cloud and local AI providers, giving you the best of both worlds.
*   **Production-Ready:** This isn’t just a demo. It’s a battle-tested, production-ready solution.
*   **Cost-Effective:** With local AI, you can have predictable costs without per-minute charges.

## ✨ Features

- **Modular AI Providers**: Easily switch between cloud and local AI providers.
  - ✅ **Deepgram Voice Agent**: Fully implemented for a powerful cloud-based solution.
  - ✅ **OpenAI Realtime**: Works out of the box—just set `OPENAI_API_KEY` in `.env` and select the OpenAI template/provider.
  - ✅ **Local AI Server**: A dedicated container that runs local models (Vosk for STT, Llama for LLM, and Piper for TTS) for full control and privacy.
- **High-Performance Architecture**: A lean `ai-engine` for call control and a separate `local-ai-server` for heavy AI processing ensures stability and scalability.
- **Hybrid ARI Architecture**: Call control using ARI with "answer caller → create mixing bridge → add caller → create ExternalMedia and add it to bridge" flow.
- **SessionStore State Management**: Centralized, typed store for all call session state, replacing legacy dictionary-based state management.
- **Real-time Communication**: ExternalMedia RTP upstream capture from Asterisk with ARI-commanded file-based playback; engine↔AI servers use WebSocket.
- **Docker-based Deployment**: Simple, two-service orchestration using Docker Compose.
- **Customizable**: Configure greetings, AI roles, and voice personalities in a simple YAML file.

## 🎥 Demo

[![Watch the demo](https://img.youtube.com/vi/ZQVny8wfCeY/hqdefault.jpg)](https://youtu.be/ZQVny8wfCeY "Asterisk AI Voice Agent demo")


## 🚀 Quick Start

Follow these 3 steps to get a working agent.

1) Clone and install
```bash
git clone https://github.com/hkjarral/Asterisk-AI-Voice-Agent.git
cd Asterisk-AI-Voice-Agent
./install.sh
```
Pick a config template when prompted. The installer will set up the media path symlink and optionally start services.

2) Verify health
```bash
curl http://127.0.0.1:15000/health
```
Expect `"audiosocket_listening": true`.

3) FreePBX dialplan (AudioSocket-first)
Add the context from `docs/FreePBX-Integration-Guide.md` (`from-ai-agent`, etc.), then route a test call to it.

Hello World (optional, Local AI):
```bash
python3 tests/test_local_ai_server_protocol.py  # With local-ai-server running
```
Should report `3/3` tests passed.

#### OpenAI Realtime quick start (cloud-only)

If you want to use OpenAI Realtime out of the box:

1) During `./install.sh`, select the OpenAI template when prompted (it writes `config/ai-agent.openai-agent.yaml` to `config/ai-agent.yaml`).
2) Add your API key in `.env`:
   ```bash
   echo "OPENAI_API_KEY=sk-..." >> .env
   ```
3) Start just the engine (no local models needed):
   ```bash
   docker-compose up -d ai-engine
   ```
4) Route a test call as in the FreePBX guide.

### Prerequisites

- **Asterisk 18+** or **FreePBX 15+** with ARI enabled.
- **Docker** and **Docker Compose** installed.
- **Git** for cloning the repository.

#### Prerequisite checks

- Verify required Asterisk modules are loaded:
  ```bash
  asterisk -rx "module show like res_ari_applications"
  asterisk -rx "module show like app_audiosocket"
  ```
  Expect both to show Status: Running. If Asterisk < 18, upgrade or on FreePBX Distro run: `asterisk-switch-version` (aka `asterisk-version-switch`) to select 18+.

  Example output:
  ```
  Module                         Description                               Use Count  Status   Support Level
  res_ari_applications.so        RESTful API module - Stasis application   0          Running  core
  1 modules loaded

  Module                         Description                               Use Count  Status   Support Level
  app_audiosocket.so             AudioSocket Application                    20         Running  extended
  1 modules loaded
  ```

- Quick install Docker
  - Ubuntu (convenience script):
    ```bash
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker $USER && newgrp docker
    docker --version && docker compose version
    ```
  - CentOS/Rocky/Alma (repo method):
    ```bash
    sudo dnf -y install dnf-plugins-core
    sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
    sudo dnf install -y docker-ce docker-ce-cli containerd.io
    sudo systemctl enable --now docker
    docker --version && docker compose version
    ```

### Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/hkjarral/Asterisk-AI-Voice-Agent.git
    cd Asterisk-AI-Voice-Agent
    ```

2.  **Run the installer (recommended)**:
    ```bash
    ./install.sh
    ```
    The installer will:
    - Verify Docker, detect Compose (`docker-compose` vs `docker compose`).
    - Run Asterisk module preflight checks.
    - Copy `.env.example` to `.env` (if needed) and prompt for ARI and API keys.
    - Let you pick a config template under `config/` and write `config/ai-agent.yaml`.
    - Offer to download local models if you choose a Local/Hybrid profile.
    - Optionally build and start the stack.

    If you prefer manual setup, follow the steps in the Configuration section below.

3.  **Start the services** (if you didn’t let the installer do it):
    ```bash
    docker-compose up --build -d
    ```
    This will start both the `ai-engine` and the `local-ai-server`. If you only want to use a cloud provider like Deepgram, you can start just the engine: `docker-compose up -d ai-engine`.


## ⚙️ Configuration

The system is configured via `config/ai-agent.yaml` and a `.env` file for secrets.

### Canonical persona and greeting

- The canonical source for the agent greeting and persona lives in `config/ai-agent.yaml` under the `llm` block:
  - `llm.initial_greeting`
  - `llm.prompt`
- Precedence rules at runtime:
  1) Provider or pipeline-specific overrides (e.g., `providers.openai_realtime.instructions` or `providers.deepgram.greeting`) if explicitly set
  2) `llm.prompt` and `llm.initial_greeting` in YAML
  3) Environment variables `AI_ROLE` and `GREETING` as defaults

This ensures all providers and pipelines stay aligned unless you intentionally override them per provider/pipeline.

### Installer behavior (GREETING/AI_ROLE)

- [`./install.sh`](install.sh) prompts for Greeting and AI Role and writes them to [`.env`](.env.example). It also updates [`config/ai-agent.yaml`](config/ai-agent.yml) `llm.*` via `yq` (Linux-first) or appends a YAML `llm` block as a fallback when `yq` cannot be installed.
- Reruns are idempotent: prompts are prefilled from existing `.env`.
- `${VAR}` placeholders in YAML remain supported; the loader expands these at runtime.

### Key `ai-agent.yaml` settings:
- `default_provider`: `openai_realtime` (monolithic fallback; pipelines are the default path via `active_pipeline`)
- `asterisk`: Connection details for ARI.
- `providers`: Specific configurations for each AI provider.

For a full, option-by-option reference (with recommended ranges and impact), see [`docs/Configuration-Reference.md`](docs/Configuration-Reference.md). For practical presets, see [`docs/Tuning-Recipes.md`](docs/Tuning-Recipes).

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

## 🎯 Current Status

-   ✅ **PRODUCTION READY**: Full two-way conversation system working perfectly!
-   ✅ **Real-time Audio Processing**: ExternalMedia RTP with SSRC mapping
-   ✅ **State Management**: SessionStore-based centralized state management
-   ✅ **TTS Gating**: Perfect feedback prevention during AI responses
-   ✅ **Local AI Integration**: Vosk STT, TinyLlama LLM, Piper TTS
-   ✅ **Conversation Flow**: Complete STT → LLM → TTS pipeline working
-   ✅ **Architecture Validation**: Refactored codebase with clean separation of concerns
-   ✅ **Observability**: ConversationCoordinator drives `/health` + `/metrics` (Prometheus friendly)



## 🗺️ Roadmap

Current milestones and acceptance criteria live in [`docs/plan/ROADMAP.md`](docs/plan/ROADMAP.md). Update that file after each deliverable so anyone (or any AI assistant) can resume the project with a single reference.

## 🤝 Contributing

Contributions are welcome! Please see our [Contributing Guide](CONTRIBUTING.md) for more details on how to get involved.

## 💬 Community

Have questions or want to chat with other users? Join our community:

*   [GitHub Issues](https://github.com/hkjarral/Asterisk-AI-Voice-Agent/issues)
*   Community Forum (coming soon)

## 📝 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## 🙏 Show Your Support

If you find this project useful, please give it a ⭐️ on [GitHub](https://github.com/hkjarral/Asterisk-AI-Voice-Agent)! It helps us gain visibility and encourages more people to contribute.

