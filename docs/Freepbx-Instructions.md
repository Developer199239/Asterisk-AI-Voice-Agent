# FreePBX Integration Guide (Manual Multi-Instance Method)

**Note:** This document describes a manual, advanced setup for running multiple, isolated instances of the AI Voice Agent to connect with different AI providers. The officially recommended method is to use the built-in provider selection mechanism. This guide is provided for power-users and for reference.

## 1. Overview

This guide explains how to run three separate instances of the AI Voice Agent container, each configured for a different AI provider (Deepgram, OpenAI, Local), and how to route calls to them from FreePBX.

## 2. Prerequisites

-   A working FreePBX installation.
-   Docker and Docker Compose installed on the same server.
-   The AI Voice Agent project cloned to a directory (e.g., `/root/Asterisk-AI-Voice-Agent`).

## 3. Configuration

### Step 3.1: Create Separate Configuration Files

Create three separate `.env` files, one for each provider.

**File 1: `.env.deepgram`**
```
AI_PROVIDER=deepgram
DEEPGRAM_API_KEY=YOUR_DEEPGRAM_KEY
OPENAI_API_KEY=YOUR_OPENAI_KEY_FOR_LLM
# ... other common settings ...
```

**File 2: `.env.openai`**
```
AI_PROVIDER=openai
OPENAI_API_KEY=YOUR_OPENAI_KEY
# ... other common settings ...
```

**File 3: `.env.local`**
```
AI_PROVIDER=local
# ... No API keys needed ...
# ... other common settings ...
```

### Step 3.2: Create Separate Docker Compose Files

Create three `docker-compose` files. The key is to map a different host port for the `/health` check for each instance to avoid conflicts.

**File 1: `docker-compose.deepgram.yml`**
```yaml
version: "3.8"
services:
  ai-agent-deepgram:
    build: .
    container_name: ai-agent-deepgram
    env_file: .env.deepgram
    ports:
      - "15001:15000" # Map container port 15000 to host port 15001
    # ... other common settings ...
```

**File 2: `docker-compose.openai.yml`**
```yaml
version: "3.8"
services:
  ai-agent-openai:
    build: .
    container_name: ai-agent-openai
    env_file: .env.openai
    ports:
      - "15002:15000" # Map to host port 15002
    # ... other common settings ...
```

**File 3: `docker-compose.local.yml`**
```yaml
version: "3.8"
services:
  ai-agent-local:
    build: .
    container_name: ai-agent-local
    env_file: .env.local
    ports:
      - "15003:15000" # Map to host port 15003
    # ... other common settings ...
```

## 4. Running the Services

Start each service in a separate terminal or as detached processes.

```bash
docker-compose -f docker-compose.deepgram.yml up -d
docker-compose -f docker-compose.openai.yml up -d
docker-compose -f docker-compose.local.yml up -d
```

You should now have three separate AI agent containers running.

## 5. FreePBX Configuration

### Step 5.1: Create ARI Users

In FreePBX, navigate to **Settings -> Asterisk REST Interface Users**. Create a unique ARI user for each AI provider instance.

-   **User:** `deepgram_agent`, Password: `...`, App: `deepgram-ai`
-   **User:** `openai_agent`, Password: `...`, App: `openai-ai`
-   **User:** `local_agent`, Password: `...`, App: `local-ai`

Update your `.env` files with the correct ARI credentials and app names for each instance.

### Step 5.2: Create Custom Destinations

Navigate to **Admin -> Custom Destinations**. Create a destination for each AI agent.

-   **Destination 1:**
    -   **Target:** `custom-ai-agents,1001,1`
    -   **Description:** `Deepgram AI Agent`
-   **Destination 2:**
    -   **Target:** `custom-ai-agents,1002,1`
    -   **Description:** `OpenAI AI Agent`
-   **Destination 3:**
    -   **Target:** `custom-ai-agents,1003,1`
    -   **Description:** `Local AI Agent`

### Step 5.3: Create Custom Dialplan

You need to add a custom context to your FreePBX dialplan. You can do this by editing the `extensions_custom.conf` file.

Add the following context:

```
[custom-ai-agents]
; Route to Deepgram
exten => 1001,1,NoOp(Routing to Deepgram AI)
 same => n,Stasis(deepgram-ai)
 same => n,Hangup()

; Route to OpenAI
exten => 1002,1,NoOp(Routing to OpenAI AI)
 same => n,Stasis(openai-ai)
 same => n,Hangup()

; Route to Local
exten => 1003,1,NoOp(Routing to Local AI)
 same => n,Stasis(local-ai)
 same => n,Hangup()
```

After adding this, reload the dialplan from the Asterisk CLI: `dialplan reload`.

### Step 5.4: Route Calls to the Agents

You can now route calls to your AI agents from anywhere in FreePBX (e.g., an IVR, a Ring Group, or an Inbound Route) by directing the call to the Custom Destination you created.

This setup allows you to test the different AI providers by simply changing the destination of an inbound call route in the FreePBX GUI.
