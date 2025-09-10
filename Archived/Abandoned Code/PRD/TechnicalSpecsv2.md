# **Technical Design Specification: Asterisk AI Agent v2.0**

* **Version:** 1.0  
* **Status:** Draft  
* **Author:** Asterisk AI Voice Agent (Expert Developer Persona)  
* **Related PRD:** prd-ai-agent-v2.md  
* **Date:** 2025-09-07

### **1\. Introduction**

This document provides the detailed technical design for implementing the v2.0 architecture outlined in the corresponding Product Requirements Document (PRD). It defines the specific libraries, data structures, API contracts, and interaction flows required for development. The goal is to provide a clear, actionable blueprint for the engineering team and AI taskmaster.

### **2\. Core Technology Stack**

| Component | Technology/Library | Rationale |
| :---- | :---- | :---- |
| **Containerization** | Docker, Docker Compose | Aligns with PRD for single-unit deployment. |
| **Message Bus** | Redis (via redis-py library) | Lightweight, fast, and ideal for Pub/Sub messaging between services. |
| **ARI Client** | ari-py (asyncio-based) | A well-maintained, asynchronous library that fits an event-driven architecture. |
| **Media Proxy** | rtpengine | A production-grade, highly performant media proxy that handles RTP complexities. |
| **rtpengine Control** | Custom Python UDP client (using asyncio.datagram\_transport) | rtpengine is controlled by the ng protocol, which is a simple UDP exchange. |
| **Audio Processing** | py-webrtcvad, pydub | Re-use existing, proven components for VAD and basic audio manipulation. |
| **Configuration** | python-dotenv | For loading the .env file in each service. |

### **3\. Inter-Service Communication: API Contracts (Redis)**

All messages published to Redis will be JSON strings. The following schemas are defined as the contract between services.

#### **3.1. calls:new**

* **Publisher:** call\_controller  
* **Purpose:** Announce a new call has been answered and is ready for media processing.  
* **Schema:**  
  {  
    "event\_type": "call\_new",  
    "channel\_id": "1678886400.123",  
    "caller\_id": "5551234567"  
  }

#### **3.2. stt:transcription:complete**

* **Publisher:** stt\_service  
* **Purpose:** Publish a final transcription after the user has stopped speaking.  
* **Schema:**  
  {  
    "event\_type": "transcription\_complete",  
    "channel\_id": "1678886400.123",  
    "transcript": "Hello, I'd like to book an appointment.",  
    "confidence": 0.98  
  }

#### **3.3. stt:vad:activity (For Barge-in)**

* **Publisher:** stt\_service  
* **Purpose:** Announce voice activity for implementing barge-in.  
* **Channel:** stt:vad:activity  
* **Schema:**  
  {  
    "event\_type": "vad\_activity",  
    "channel\_id": "1678886400.123",  
    "status": "speaking" // or "silence"  
  }

#### **3.4. llm:response:ready**

* **Publisher:** llm\_service  
* **Purpose:** Publish the AI's text response.  
* **Schema:**  
  {  
    "event\_type": "llm\_response\_ready",  
    "channel\_id": "1678886400.123",  
    "text": "Of course, I can help with that. For what day and time?"  
  }

#### **3.5. calls:control:play**

* **Publisher:** tts\_service  
* **Purpose:** Instruct the call\_controller to play a synthesized audio file.  
* **Schema:**  
  {  
    "event\_type": "playback\_request",  
    "channel\_id": "1678886400.123",  
    "media\_uri": "file:///shared/audio/1678886400.123-response-1.slin16"  
  }

### **4\. Service-Specific Design**

#### **4.1. call\_controller Service**

* **Core Logic:** Will be an asyncio application.  
* **State Management:** Will maintain an in-memory dictionary to track the state of each active call.  
  \# Example call\_states dictionary  
  call\_states \= {  
      "1678886400.123": {  
          "state": "SPEAKING", \# IDLE, LISTENING, SPEAKING  
          "caller\_id": "5551234567",  
          "active\_playback\_id": "playback-uuid-123"  
      }  
  }

* **rtpengine Interaction:**  
  1. On StasisStart, it will receive the initial SDP from Asterisk.  
  2. It will send an offer command to rtpengine via its UDP control port, including the Asterisk SDP and the command to fork media to the stt\_service.  
     * rtpengine offer command will include: {'replace': \['origin', 'session-connection'\], 'fork-media-to': 'udp:stt\_service:5004'}  
  3. rtpengine will respond with a new SDP containing its media port.  
  4. The call\_controller will send this new SDP back to Asterisk in the answer call on the ARI channel.

#### **4.2. stt\_service Service**

* **Media Reception:** Will run a simple UDP server on a fixed port (e.g., 5004\) to receive the raw RTP stream forked from rtpengine. It will not send any packets back.  
* **Audio Processing:**  
  1. Packets will be de-packetized (RTP headers removed).  
  2. The payload (G.711 u-law/a-law) will be decoded to LPCM (16-bit, 8000Hz). Logic from the existing codec\_handler.py will be reused.  
  3. The PCM audio will be fed into the VAD algorithm.  
* **Barge-in Logic:**  
  1. The service will continuously monitor VAD state.  
  2. When the state changes from silence to speaking, it will immediately publish a stt:vad:activity message with status: "speaking".  
  3. The call\_controller will subscribe to this and, if the call state is SPEAKING, will immediately issue a stop command for the active playback on ARI.

#### **4.3. llm\_service Service**

* **Conversation History:** Will use Redis to store conversation history. A Redis Hash is suitable, with the channel\_id as the key.  
  HSET call:history:1678886400.123 user\_1 "Hello..."  
  HSET call:history:1678886400.123 ai\_1 "Hi, how can I help?"

* This ensures that if the llm\_service restarts, it can pick up the conversation where it left off (stateless service).

#### **4.4. tts\_service Service**

* **Audio Storage:** A Docker volume will be shared between the tts\_service and the call\_controller service, mounted at a path like /shared/audio.  
* **Workflow:**  
  1. Receives llm:response:ready message.  
  2. Synthesizes the text into audio. **The output format must be compatible with Asterisk playback (e.g., 16-bit signed linear PCM, .slin16).**  
  3. Saves the file to the shared volume with a unique name (e.g., {channel\_id}-{timestamp}.slin16).  
  4. Publishes a calls:control:play message with the file:// URI pointing to the new file.

### **5\. Proposed Project Directory Structure**

To accommodate the microservices architecture, the project will be restructured:

/asterisk-ai-voice-agent  
|-- /services  
|   |-- /call\_controller  
|   |   |-- main.py  
|   |   \`-- Dockerfile  
|   |-- /stt\_service  
|   |   |-- main.py  
|   |   \`-- Dockerfile  
|   |-- /llm\_service  
|   |   |-- main.py  
|   |   \`-- Dockerfile  
|   |-- /tts\_service  
|   |   |-- main.py  
|   |   \`-- Dockerfile  
|-- /shared  
|   \`-- /audio\_processing \# Common code like codecs, VAD can live here  
|-- docker-compose.yml  
|-- .env  
\`-- README.md

### **6\. Barge-In Sequence Diagram**

This flow details how an interruption is handled:

1. **tts\_service \-\> Redis:** Publishes calls:control:play with audio URI.  
2. **Redis \-\> call\_controller:** Receives the message.  
3. **call\_controller:** Sets call\_state for the channel to SPEAKING.  
4. **call\_controller \-\> Asterisk (ARI):** Issues channels.play(media=URI). AI starts speaking.  
5. **User \-\> Asterisk \-\> rtpengine \-\> stt\_service:** User starts speaking. Audio is streamed to stt\_service.  
6. **stt\_service:** VAD detects speech.  
7. **stt\_service \-\> Redis:** Publishes stt:vad:activity with status: "speaking".  
8. **Redis \-\> call\_controller:** Receives the VAD activity message.  
9. **call\_controller:** Checks call\_state. It's SPEAKING, so this is a barge-in.  
10. **call\_controller \-\> Asterisk (ARI):** Issues playbacks.stop() for the active playback.  
11. **call\_controller:** Sets call\_state to LISTENING.  
12. **(Normal flow continues):** The stt\_service will eventually publish the full transcription, which the llm\_service will process.

This Technical Design Specification provides the necessary detail to begin the phased implementation of the v2.0 architecture.