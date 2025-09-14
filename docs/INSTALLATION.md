# Asterisk AI Voice Agent - Installation Guide

This guide provides detailed instructions for setting up the Asterisk AI Voice Agent on your server.

## 1. Prerequisites

Before you begin, ensure your system meets the following requirements:

-   **Operating System**: A modern Linux distribution (e.g., Ubuntu 20.04+, CentOS 7+).
-   **Asterisk**: Version 16 or newer. FreePBX 15+ is also supported.
-   **ARI (Asterisk REST Interface)**: Enabled and configured on your Asterisk server.
-   **Docker**: Latest stable version of Docker and Docker Compose.
-   **Git**: Required to clone the project repository.
-   **Network Access**: Your server must be able to make outbound connections to the internet for Docker image downloads and API access to AI providers.

## 2. Installation Steps

The installation is handled by an interactive script that will guide you through the process.

### Step 2.1: Clone the Repository

First, clone the project repository to a directory on your server.

```bash
git clone https://github.com/your-repo/asterisk-ai-voice-agent.git
cd asterisk-ai-voice-agent
```

### Step 2.2: Run the Installation Script

Execute the `install.sh` script. You will need to run it with `sudo` if your user does not have permissions to run Docker.

```bash
./install.sh
```

The script will perform the following actions:

1.  **System Checks**: Verify that Docker is installed and running.
2.  **Interactive Setup**: Launch a wizard to collect configuration details.

### Step 2.3: Interactive Setup Wizard

The wizard will prompt you for the following information.

#### AI Provider Selection

You will be asked to choose an AI provider.

-   **[1] Deepgram Voice Agent (Recommended)**: An all-in-one provider for real-time, high-quality conversations. This is the only option fully implemented in the current version.
-   **[2] OpenAI Stack**: A modular option using OpenAI's services for STT, LLM, and TTS. (In development)
-   **[3] Local Models**: An offline option for privacy and no recurring costs. (Planned)

#### Provider Configuration

Based on your selection, you will need to provide API keys.

-   **Deepgram API Key**: Required if you select the Deepgram provider.
-   **OpenAI API Key**: Required for both Deepgram (for the LLM) and the planned OpenAI provider.

#### Asterisk ARI Configuration

You will need to provide the connection details for your Asterisk server's ARI.

-   **Asterisk Host**: The hostname or IP address of your Asterisk server.
-   **ARI Username**: The username for an ARI user.
-   **ARI Password**: The password for the ARI user.

#### Business Configuration

Customize the AI's personality.

-   **Company Name**: The name of your company (e.g., "Jugaar LLC").
-   **AI Role**: The role the AI will play (e.g., "Customer Service Assistant").
-   **Greeting**: The initial greeting the AI will say to the caller.

### Step 2.4: Configuration File Generation

After you complete the wizard, the script will create a `.env` file in the project root with all your settings. You can manually edit this file later if you need to make changes.

### Step 2.5: Start the Service

Once the configuration is complete, the script will prompt you to build and start the Docker container. You can also do this manually.

```bash
docker-compose up --build -d
```

## 3. Verifying the Installation

After starting the service, you can check that it is running correctly.

### Check Docker Container Status

```bash
docker-compose ps
```

You should see the `ai-engine` and `local-ai-server` containers running.

### Check Container Logs

```bash
docker-compose logs -f ai-engine
```

Look for a message indicating a successful connection to the Asterisk ARI and that the AudioSocket listener is ready on port 8090.

### Make a Test Call (AudioSocket + Stasis)

Use an AudioSocket-first dialplan so Asterisk streams raw audio to the agent before handing control to the Stasis app.

**Example Dialplan (`extensions.conf`):**

```
[from-internal]
exten => 1234,1,NoOp(Sending call to AI Voice Agent)
 same => n,Set(AUDIOSOCKET_HOST=127.0.0.1)
 same => n,Set(AUDIOSOCKET_PORT=8090)
 same => n,AudioSocket(${AUDIOSOCKET_HOST}:${AUDIOSOCKET_PORT},ulaw)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

## 4. Troubleshooting

-   **Cannot connect to ARI**:
    -   Verify that your Asterisk `host`, `username`, and `password` are correct in the `.env` file.
    -   Ensure that the ARI port (usually 8088) is accessible from the Docker container.
    -   Check your `ari.conf` and `http.conf` in Asterisk.
-   **AI does not respond**:
    -   Check that your API keys in the `.env` file are correct.
    -   View the container logs (`docker-compose logs -f ai-engine`) for any provider/API errors.
-   **Audio Quality Issues**:
    -   Confirm AudioSocket is connected (see Asterisk CLI and `ai-engine` logs).
    -   Use a tmpfs for media files (e.g., `/mnt/asterisk_media`) to minimize I/O latency for file-based playback.
    -   Verify you are not appending file extensions to ARI `sound:` URIs (Asterisk will add them automatically).

For more advanced troubleshooting, refer to the project's main `README.md` or open an issue in the repository.
