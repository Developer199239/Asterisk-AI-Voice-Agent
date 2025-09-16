# Gemini.md — My Build & Ops Guide

This document outlines my understanding of the project and the procedures I will follow to contribute effectively. It is based on the excellent `Agents.md` and the project's rule files.

## My Mission & Scope
My primary mission is to **establish a functional two-way conversation with the local AI provider.**

The immediate goal is to ensure that a user can speak to the AI and receive a spoken response, completing the full audio-in -> AI -> audio-out loop. Achieving a functional pipeline is the priority, even if the initial version has noticeable latency.

## My Architectural Understanding
I understand the project is a modular, two-container system:

1.  **`ai-engine`**: The core orchestrator. It connects to Asterisk via ARI for call control and uses a dedicated `AudioSocket` TCP server for reliable, real-time audio capture from the caller.
2.  **`local-ai-server`**: A separate container that hosts the local AI models (Vosk, Llama, Piper). It communicates with the `ai-engine` via a WebSocket connection.

The core data flow for my mission is:
*   **Audio Input**: Caller -> Asterisk -> `AudioSocket` -> `ai-engine` -> `LocalProvider` -> `local-ai-server`.
*   **Audio Output**: `local-ai-server` -> `LocalProvider` -> `ai-engine` -> Save to file -> ARI command to play the file to the Caller.

## My Development & Deployment Workflow

I will follow the established workflow for this project:

1.  **Branch**: I will perform all work directly on the `develop` branch.
2.  **Code Changes**: I will make code changes to the local files in the project directory.
3.  **Committing Code**: I will commit my changes to the `develop` branch. It is your responsibility to push these changes to the `origin` remote.

### Deployment Environment
*   **Server**: `root@voiprnd.nemtclouddispatch.com`
*   **Project Folder**: `/root/Asterisk-Agent-Develop`

My deployment process will be to provide you with the necessary shell commands to execute on this server. A typical deployment will involve pulling the latest changes from the `develop` branch and restarting the appropriate Docker containers.

## Key Commands I Will Use

*   **Local Restart for `ai-engine`**: `docker-compose restart ai-engine`
*   **Local Rebuild for Dependencies**: `docker-compose up --build -d`
*   **View Logs**: `docker-compose logs -f ai-engine` and `docker-compose logs -f local-ai-server`
*   **Check Service Status**: `docker-compose ps`

## Mission Focus Areas

To achieve a functional two-way conversation, I will focus on these technical areas:

1.  **Verify the Audio Input Path**: Ensure the raw audio from the `AudioSocket` is correctly received by the `engine` and passed to the `LocalProvider`.
2.  **Trace the AI Pipeline**: Confirm that the `local-ai-server` receives the audio, successfully transcribes it (STT), gets a response from the language model (LLM), and synthesizes a reply (TTS).
3.  **Verify the Audio Output Path**: Ensure the TTS audio from the provider is received by the `ai-engine`, saved to the shared media directory, and that the ARI `play` command is successfully executed.
4.  **Instrument with Logging**: Add clear and concise logging at each major step of the conversation loop to trace the flow of data and identify points of failure or significant delay.

## My Troubleshooting Procedure

When debugging a failed call, I will follow this systematic procedure:

1.  **Clear Logs**: I will ask you to clear all existing logs from the `ai-engine` and `local-ai-server` containers to ensure a clean slate for the test.
2.  **Tail Logs**: I will ask you to simultaneously tail the logs from both containers and the Asterisk full log (`/var/log/asterisk/full`) during a test call and provide me the output.
3.  **Create Timeline**: After the call, I will create a detailed, timestamped timeline of events. This timeline will correlate the logs from all three sources with the code's execution path.
4.  **Analyze and Decide**: Based on the timeline, I will identify what worked and what failed, pinpoint the exact point of failure, and decide on the most effective next step to resolve the issue.

---
*This is a living document. I will update it whenever I learn something new that will help me contribute to the project more effectively.*
