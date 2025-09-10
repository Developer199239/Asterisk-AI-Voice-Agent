# Asterisk AI Voice Agent v3.0

An open-source AI Voice Agent that integrates with Asterisk/FreePBX using the Asterisk REST Interface (ARI) and a modular, plug-and-play AI provider architecture.

## 🌟 Features

- **Modular AI Providers**: Easily switch between different AI providers.
  - ✅ **Deepgram Voice Agent**: Currently implemented and working.
  - 🔄 **OpenAI Stack**: In development.
  - 📋 **Local Models**: Planned for future releases (Vosk, Llama, Piper).
- **ARI Integration**: Robust integration with Asterisk 16+ using ARI for call control and media streaming.
- **Real-time Communication**: Low-latency, real-time conversation flow.
- **Docker-based Deployment**: Simple, single-container deployment using Docker Compose.
- **Customizable**: Configure business-specific greetings, AI roles, and voice personalities.

## 🚀 Quick Start

### Prerequisites

- **Asterisk 16+** or **FreePBX 15+** with ARI enabled.
- **Docker** and **Docker Compose** installed.
- **Git** for cloning the repository.

### Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/your-repo/asterisk-ai-voice-agent.git
    cd asterisk-ai-voice-agent
    ```

2.  **Run the interactive installation script**:
    ```bash
    ./install.sh
    ```
    This script will guide you through the configuration process, including setting up your AI provider, Asterisk connection, and business details. It will create a `.env` file with your configuration.

3.  **Start the service**:
    ```bash
    docker-compose up --build -d
    ```

For more detailed instructions, see [docs/INSTALLATION.md](docs/INSTALLATION.md).

## ⚙️ Configuration

The system is configured using a `.env` file in the project root. The `install.sh` script will help you create this file.

### Required Environment Variables

- `AI_PROVIDER`: The AI provider to use (`deepgram`, `openai`, `local`).
- `ASTERISK_HOST`: Your Asterisk server's hostname or IP address.
- `ASTERISK_ARI_USERNAME`: ARI username.
- `ASTERISK_ARI_PASSWORD`: ARI password.
- `CONTAINER_HOST_IP`: The IP address of the server running the Docker container.
- `OPENAI_API_KEY`: Your OpenAI API key (used by Deepgram and OpenAI providers).
- `DEEPGRAM_API_KEY`: Your Deepgram API key (if using the `deepgram` provider).

## 🏗️ Project Architecture

The application runs in a single Docker container (`call_controller`) and uses Redis for messaging. It connects to Asterisk via ARI and to your chosen AI provider.

```
┌──────────────────┐      ┌────────────────────┐      ┌──────────────────┐
│ Asterisk Server  │◀────▶│ AI Voice Agent     │◀────▶│ AI Provider      │
│ (ARI, RTP)       │      │ (Docker Container) │      │ (Deepgram, etc.) │
└──────────────────┘      └────────────────────┘      └──────────────────┘
```

For a detailed architecture diagram, see the [Product Requirements Document](Project%20Requirement%20Documents/prd-ai-agent-v3.md).

## 🧑‍💻 Development Workflow

1.  **Local Development**: Make code changes in your local environment.
2.  **Git Workflow**: Commit and push changes to the repository.
3.  **Server Deployment**: Pull the latest changes on your server and restart the Docker container.

### Test Server

-   **Server**: `root@voiprnd.nemtclouddispatch.com`
-   **Asterisk**: 16+ with FreePBX UI.
-   **Docker**: Available for testing.

##  roadmap

Our development roadmap is structured in phases. See the [Implementation Phases](Project%20Requirement%20Documents/prd-ai-agent-v3.md#7-implementation-phases) in the PRD for details.

-   ✅ **Phase 1 & 2**: Core Infrastructure & Deepgram POC (Completed)
-   ▶️ **Phase 3**: Provider Architecture (In Progress)
-   ⏩ **Phase 4**: Local AI Integration (Next)

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a pull request.

1.  Fork the repository.
2.  Create a feature branch (`git checkout -b feature/your-feature`).
3.  Commit your changes (`git commit -m 'Add some feature'`).
4.  Push to the branch (`git push origin feature/your-feature`).
5.  Open a pull request.

## 📄 License

This project is licensed under the MIT License. See the `LICENSE` file for details.


