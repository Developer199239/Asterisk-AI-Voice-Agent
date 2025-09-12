# Asterisk AI Voice Agent v3.0

An open-source AI Voice Agent that integrates with Asterisk/FreePBX using the Asterisk REST Interface (ARI). It now features a **two-container, modular architecture** that allows for plug-and-play AI providers, including a dedicated server for local models for real-time, natural conversations.

## 🌟 Features

- **Modular AI Providers**: Easily switch between cloud and local AI providers.
  - ✅ **Deepgram Voice Agent**: Fully implemented for a powerful cloud-based solution.
  - ✅ **Local AI Server**: A dedicated container that runs local models (Vosk for STT, Llama for LLM, and Piper for TTS) for full control and privacy.
- **High-Performance Architecture**: A lean `ai-engine` for call control and a separate `local-ai-server` for heavy AI processing ensures stability and scalability.
- **Real-time Communication**: Low-latency conversation flow achieved via direct WebSocket communication between the engine and the AI servers.
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

3.  **Start the services**:
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

This separation ensures that the resource-intensive AI models do not impact the real-time call handling performance of the `ai-engine`.

## 🧑‍💻 Development Workflow

The two-container setup enables a rapid development workflow.

-   **For `ai-engine` code changes**: `docker-compose restart ai-engine` (takes seconds).
-   **For `local-ai-server` changes**: `docker-compose restart local-ai-server`.
-   **For dependency changes**: `docker-compose up --build -d`.

Source code for the `ai-engine` is mounted as a volume, so there's no need to rebuild the image for simple Python code changes.

### Test Server

-   **Production Directory**: `/root/Asterisk-AI-Voice-Agent` (runs `main` branch)
-   **Development Directory**: `/root/Asterisk-Agent-Develop` (runs `develop` branch)
-   **Server**: `root@voiprnd.nemtclouddispatch.com`

##  Roadmap

-   ✅ **Phase 1 & 2**: Core Infrastructure & Deepgram POC (Completed)
-   ✅ **Phase 3**: Provider Architecture Refactor (Completed)
-   ✅ **Phase 4**: Local AI Integration (Completed)

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a pull request.

1.  Fork the repository.
2.  Create a feature branch (`git checkout -b feature/your-feature`).
3.  Commit your changes (`git commit -m 'Add some feature'`).
4.  Push to the branch (`git push origin feature/your-feature`).
5.  Open a pull request.

## 📄 License

This project is licensed under the MIT License. See the `LICENSE` file for details.


