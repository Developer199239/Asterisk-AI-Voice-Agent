# **PRD: Asterisk AI Voice Agent v2.0 \- Architectural Evolution**

* **Version:** 1.2  
* **Status:** Complete  
* **Author:** Asterisk AI Voice Agent (Expert Developer Persona)  
* **Stakeholders:** Project Owner
* **Related Technical Specs:** TechnicalSpecsv2.md    
* **Date:** 2025-09-07

### **1\. Introduction**

The initial version of the Asterisk AI Voice Agent successfully proved the core concept of integrating a conversational AI with Asterisk using a monolithic SIP client architecture. While effective for single-call scenarios, this design presents challenges in scalability, resilience, and maintainability. To evolve the project into a robust, production-ready solution, a fundamental architectural shift is required.

This document outlines the requirements for refactoring the application to an event-driven, microservices-based architecture orchestrated within a single Docker container. The new architecture will leverage the **Asterisk REST Interface (ARI)**, moving from emulating a phone (SIP) to directly controlling the PBX (ARI), resulting in a far more powerful and native integration.

### **2\. The Problem**

The current architecture, where the application acts as a single SIP endpoint, has the following limitations:

* **Scalability Bottleneck:** A single Python process handles SIP signaling, media processing, and all AI provider interactions. This makes handling multiple concurrent calls inefficient and prone to performance degradation.  
* **Tight Coupling:** The call logic (conversation\_loop.py) is tightly bound to the SIP client (sip\_client.py) and audio processing. Changes to one part of the system have a high risk of impacting others.  
* **Limited Resilience:** An error in any part of the process (e.g., a timeout from an OpenAI API) can jeopardize the entire call session and potentially the stability of the main application process.  
* **Complex Turn-Taking:** Managing conversation state and barge-in is complex when the application is just another endpoint on the line, rather than the controller of the line.

### **3\. Goals and Objectives**

* **Primary Goal:** Refactor the application into a decoupled, ARI-based architecture without sacrificing the simplicity of a single-container deployment.  
* **Objectives:**  
  1. **Improve Scalability:** Design the system to handle multiple concurrent calls efficiently.  
  2. **Enhance Resilience:** Isolate components and define clear fallback strategies so that a failure in one service does not crash the entire system.  
  3. **Increase Maintainability:** Decouple components into well-defined microservices, making the codebase easier to understand, test, and upgrade.  
  4. **Natural Conversation Flow:** Implement full barge-in capability for a more fluid user experience.  
  5. **Maintain Simplicity:** Ensure the end-user deployment remains a simple docker-compose up command with configuration managed through a single .env file.

### **4\. System Architecture & Functional Requirements**

The monolithic application will be broken down into several independent services that communicate via an internal message queue (Redis Pub/Sub). All services will run within the same Docker network, orchestrated by docker-compose.

#### **4.1. Core Components**

**4.1.1. Container Orchestration (docker-compose.yml)**

* **Responsibility:** Define and manage the lifecycle of all internal services.  
* **Services:**  
  * call\_controller  
  * rtpengine (External Media Proxy)  
  * stt\_service  
  * llm\_service  
  * tts\_service  
  * redis (Internal message bus)  
* **Configuration:** All user-facing configuration will be centralized in a .env file.

**4.1.2. Internal Message Queue (redis)**

* **Responsibility:** Act as the central nervous system for inter-service communication.  
* **Channels (Topics):**  
  * calls:new  
  * media:chunk:raw  
  * stt:transcription:complete  
  * llm:response:ready  
  * tts:synthesis:complete  
  * calls:control:play

**4.1.3. Call Controller Service (call\_controller)**

* **Responsibility:** The brain of the operation. Manages the call lifecycle via ARI and controls the media proxy.  
* **Replaces:** engine.py, sip\_client.py, call\_session.py.  
* **Functionality:**  
  1. Connects to the Asterisk ARI WebSocket.  
  2. On a new StasisStart event, it uses rtpengine's API to allocate ports and instructs Asterisk via ARI to send and receive media from those ports.  
  3. Publishes a calls:new event with the unique channel ID and caller ID from ARI to Redis.  
  4. Subscribes to calls:control:play to play back synthesized audio.  
  5. Implements barge-in by listening for new VAD events from the media stream while playback is active. If the user speaks, it will stop the playback via ARI.

**4.1.4. Media Proxy (rtpengine)**

* **Responsibility:** Manages the raw RTP audio streams robustly and efficiently.  
* **Replaces:** The custom media\_server concept and the audio\_processing/ directory.  
* **Functionality:**  
  1. Receives the RTP stream from Asterisk as directed by the call\_controller.  
  2. Is configured to fork a copy of the received RTP stream to the stt\_service for real-time processing.  
  3. Handles all NAT traversal and low-level RTP session management.

**4.1.5. STT Service (stt\_service)**

* **Responsibility:** Transcribes audio forked from rtpengine into text.  
* **Adapts:** src/providers/openai/stt\_handler.py.  
* **Functionality:**  
  1. Listens on a UDP port for the forked RTP stream from rtpengine.  
  2. Decodes, runs VAD, and processes the audio.  
  3. Publishes the resulting text transcription to stt:transcription:complete with the call's unique channel ID.

**4.1.6. LLM Service (llm\_service)**

* **Responsibility:** Manages the conversation logic and context.  
* **Adapts:** src/providers/openai/llm\_handler.py.  
* **Functionality:**  
  1. Subscribes to stt:transcription:complete.  
  2. Uses the channel ID to maintain the conversation history for each active call.  
  3. Publishes the LLM's text response to llm:response:ready.

**4.1.7. TTS Service (tts\_service)**

* **Responsibility:** Converts the AI's text response into speech.  
* **Adapts:** src/providers/openai/tts\_handler.py.  
* **Functionality:**  
  1. Subscribes to llm:response:ready.  
  2. Synthesizes the text to an audio file/stream.  
  3. Publishes a calls:control:play message to Redis containing the URI/path to the audio that the call\_controller can instruct Asterisk to play.

#### **4.2. Advanced Features & Requirements**

**4.2.1. Barge-in (Conversational Interruption)**

* **Requirement:** The system MUST allow a user to interrupt the AI agent while it is speaking.  
* **Implementation:** The call\_controller will monitor for new speech detection events from the media stream. Upon detection, it will issue an ARI command to stop the current audio playback immediately, allowing the STT-\>LLM-\>TTS flow to begin with the user's new input.

**4.2.2. Error Handling and Resilience**

* **STT Service Failure:** If transcription fails, the call\_controller will play a message ("I'm sorry, I didn't catch that. Could you say it again?") and re-open the listening state.  
* **LLM Service Failure:** The service will attempt a retry (e.g., up to 2 times). If it still fails, it will attempt to use a fallback LLM model if one is defined in the .env file (FALLBACK\_LLM\_MODEL). If no fallback exists or it also fails, it will play a message ("I'm having trouble connecting right now, please try again later.") and hang up.  
* **TTS Service Failure:** If the primary TTS provider fails, the system will fall back to using Asterisk's native SayAlpha function to speak the raw text response to the user, ensuring the user always receives a response.

**4.2.3. Logging and Monitoring**

* **Configurable Log Level:** The .env file will contain a LOG\_LEVEL variable (e.g., DEBUG, INFO, WARN, ERROR) that is passed to all services to control log verbosity.  
* **Performance Metrics:** At the INFO level, logs will include timing information for key operations (e.g., "STT transcription took 450ms", "LLM response received in 1.1s").  
* **Conversation Transparency:** At the DEBUG level, logs will show the full content of the conversation, including transcriptions and LLM responses, prefixed with the unique channel ID for easy tracing of a single call.  
* **Dedicated Conversation Log:** In addition to standard container output, all transcriptions and LLM responses will be written to a dedicated, structured log file (/logs/conversations.log). Each entry will be a JSON object containing channel\_id, caller\_id, timestamp, speaker (user/ai), and text.

### **5\. Deployment & User Experience**

* A .env.example file will be provided with all necessary configurations, including new fields for LOG\_LEVEL and FALLBACK\_LLM\_MODEL.  
* The user will run docker-compose up \-d.  
* The README.md will be updated with clear instructions for configuring Asterisk ari.conf, http.conf, and the extensions.conf dialplan to use the Stasis application.

### **6\. Phasing & Implementation Plan**

The implementation plan remains the same, with the main change being the integration of rtpengine in Phase 2 instead of a custom media server.

1. **Phase 1: Setup & Basic Call Control**  
2. **Phase 2: Media Integration with rtpengine**  
3. **Phase 3: Decouple STT**  
4. **Phase 4: Decouple LLM & TTS**  
5. **Phase 5: Closing the Loop & Implementing Barge-in**

### **7\. Future Roadmap (Post v2.0)**

* **v3.0 \- AI Tool Integration:** Once the core calling and conversation engine is stable, the next major evolution will be to empower the AI with tools. This will involve creating a secure framework for the llm\_service to interact with external APIs, databases, and services (e.g., calendars, CRM systems). This will allow the agent to move beyond conversational tasks to perform actions and retrieve real-time data on behalf of the user, unlocking advanced use cases like appointment booking, order status checking, and dynamic data queries.