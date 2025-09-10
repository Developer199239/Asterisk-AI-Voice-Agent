# Asterisk AI Voice Agent v3.0 - Modular Architecture
## Product Requirements Document

**Version:** 3.1
**Date:** September 10, 2025
**Status:** Active Development
**Target Release:** v3.1

---

## 1. Executive Summary

### 1.1 Project Overview
The Asterisk AI Voice Agent v3.0 is a simplified, single-container conversational AI system designed specifically for Asterisk administrators and FreePBX users. The system provides natural, high-quality voice conversations through a **modular, provider-based architecture** that prioritizes ease of deployment, maintenance, and customization.

### 1.2 Key Value Propositions
- **One-Command Deployment**: Complete setup with a single `./install.sh` command.
- **Pluggable AI Providers**: Easily switch between local, cloud, or hybrid AI providers.
- **Business-Ready**: Customizable greetings, roles, and voice personalities.
- **Resource Efficient**: A single container handles multiple providers, minimizing resource usage.
- **Cost-Effective**: Local AI models eliminate recurring API costs.

### 1.3 Success Metrics
- **Deployment Time**: < 10 minutes from clone to first call.
- **Uptime**: 99.5% availability.
- **Provider Switching**: Ability to test different AI providers by dialing different extensions, with no restart required.

---

## 2. Target Users

### 2.1 Primary Users
- **Asterisk Administrators**: Managing existing Asterisk systems
- **FreePBX Users**: Looking to add AI capabilities to their PBX
- **Linux Hobbyists**: Tech-savvy users with Asterisk experience
- **Small Business Owners**: Wanting professional AI phone systems

### 2.2 User Characteristics
- **Technical Level**: Good Linux understanding, familiar with Asterisk
- **Environment**: Existing Asterisk VMs (new or already running)
- **Goals**: Add AI voice capabilities without complex infrastructure
- **Constraints**: Limited time for setup and maintenance

---

## 3. Core Features

### 3.1 Conversational AI
- **Real-time Speech-to-Text**: Accurate transcription of caller speech
- **Natural Language Processing**: Understanding caller intent and context
- **Intelligent Responses**: Contextual, helpful responses to caller queries
- **Text-to-Speech**: High-quality, natural-sounding voice output

### 3.2 Call Management
- **Automatic Call Answering**: Seamless integration with Asterisk call flow
- **Call State Management**: Proper handling of call lifecycle events
- **DTMF Support**: Recognition of keypad input for menu navigation
- **Call Transfer**: Ability to transfer calls to human agents when needed

### 3.3 Customization
- **Custom Greetings**: Personalized welcome messages for different businesses
- **Role Definition**: Configurable AI personality and expertise areas
- **Voice Selection**: Choice between male and female voices
- **Business Context**: Industry-specific knowledge and responses

### 3.4 AI Provider Options
- **Local Mode**: Fully offline operation with local AI models
- **Cloud Mode**: High-quality cloud-based AI services
- **Hybrid Mode**: Mix of local and cloud services for optimal performance
- **Dynamic Selection**: Choose the AI provider on a per-call basis via the dialplan.

---

## 4. Technical Architecture

### 4.1 High-Level Architecture
```
┌──────────────────────────┐      ┌──────────────────────────────────────────────────┐      ┌──────────────────┐
│      Asterisk Server     │      │         Host Machine / VM (Running Docker)       │      │   AI Provider    │
│  ┌─────────────────────┐ │      │  ┌────────────────────┐  ┌─────────────────────┐ │      │  (Cloud APIs)    │
│  │     Stasis App      │ │      │  │ AI Voice Agent     │  │      ./models/      │ │      │ e.g., Deepgram,  │
│  │ 'ai-voice-agent'    ├─┼──────┼─▶│ (Docker Container) │◀─┼── (Docker Volume)  │ │◀────▶│ OpenAI           │
│  └─────────────────────┘ │      │  │                    │  │                     │ │      └──────────────────┘
│ (Sends call to Stasis)   │      │  │ ------------------ │  │ ┌─────────────────┐ │      
│                          │      │  │   src/engine.py    │  │ │ llama-2-7b.gguf │ │      
│                          │      │  │ (Orchestrator)     │  │ ├─────────────────┤ │      
│                          │      │  │ ------------------ │  │ │ vosk-model/     │ │      
│                          │      │  │   AIProvider-      │  │ ├─────────────────┤ │      
│                          │      │  │   Interface        │  │ │ piper-voice.onnx│ │      
│                          │      │  │ ------------------ │  │ └─────────────────┘ │      
│                          │      │  │ ▶ DeepgramProvider │  │ (Local Model Files) │      
│                          │      │  │ ▶ OpenAIProvider   │  └─────────────────────┘ │      
│                          │      │  │ ▶ LocalProvider    │                          │      
│                          │      │  └────────────────────┘                          │      
│                          │      └──────────────────────────────────────────────────┘      
└──────────────────────────┘
```

### 4.2 Container Architecture

-   **Single Docker Container**: All application logic runs in a single, unified container for simplicity and resource efficiency.
-   **Modular AI Providers**: The system uses a provider-based architecture, inspired by the OpenSIPS AI Connector. A core `engine.py` orchestrates calls and loads the appropriate AI provider on a per-call basis.
-   **Provider Abstraction (`AIProviderInterface`)**: All providers (Deepgram, Local, etc.) implement a common abstract base class. This contract ensures the core engine can interact with any provider using a standard set of methods (`start_session`, `send_audio`, `stop_session`), completely decoupling the engine from the specific implementation details of any one AI service.
-   **Model Management via Docker Volumes**: Large AI model files are **not** part of the Docker image. They are downloaded to a `./models` directory on the host and mounted into the container at runtime using a Docker Volume. This keeps the image size small and allows users to manage models independently of the application.
-   **Multi-Stage Dockerfile**: The `Dockerfile` will use a multi-stage build process. A `builder` stage will compile dependencies like `llama-cpp-python`, and the final, lightweight `runtime` stage will only copy the necessary compiled artifacts, resulting in a smaller and more secure production image.

### 4.3 AI Providers

#### 4.3.1 Local AI Stack
- **STT**: Vosk (offline, CPU-optimized)
- **LLM**: Llama-cpp-python with 7B-13B parameter models
- **TTS**: Piper TTS (neural, high-quality)
- **Voice Options**:
  - Male: "en_US-lessac-medium" (Professional, clear)
  - Female: "en_US-lessac-high" (Friendly, warm)

#### 4.3.2 Cloud AI Stack
- **Provider**: Deepgram Voice Agent (All-in-one STT, LLM, TTS)
- **Provider**: OpenAI (Separate STT, LLM, TTS services)
- **Voice Options**: Alloy (neutral), Nova (female), Echo (male) for OpenAI

#### 4.3.3 Hybrid AI Stack
- **STT**: Local Vosk + Cloud Deepgram fallback
- **LLM**: Local Llama + Cloud OpenAI fallback
- **TTS**: Local Piper + Cloud OpenAI fallback
- **Intelligent Fallback**: Automatic switching based on performance

---

## 5. User Experience

### 5.1 Installation Flow
```bash
# Step 1: Clone Repository
git clone https://github.com/your-repo/asterisk-ai-voice-agent
cd asterisk-ai-voice-agent

# Step 2: Run Installation
./install.sh

# What happens:
# 1. System Requirements Check
# 2. Asterisk Status & Codec Verification
# 3. Port Availability Check
# 4. Local AI Model Download (Optional)
# 5. AI Provider Configuration
# 6. Container Build and Deployment
# 7. Status Dashboard
```

---

## 6. Configuration Management

### 6.1 Configuration File Structure (`ai-agent.yaml`)
The system will be configured via a single YAML file, allowing for the definition of multiple AI providers.

```yaml
# config/ai-agent.yaml
default_provider: "local"

providers:
  deepgram:
    api_key: "${DEEPGRAM_API_KEY}"
    model: "nova-2"
    # ... deepgram specific settings

  openai:
    api_key: "${OPENAI_API_KEY}"
    model: "gpt-4o"
    voice: "alloy"
    # ... openai specific settings

  local:
    stt_model: "/app/models/stt/vosk-model..."
    llm_model: "/app/models/llm/llama-2-7b..."
    tts_voice: "/app/models/tts/en_US-lessac..."
    # ... local stack settings
```

### 6.2 Provider Selection
The AI provider for a call is selected by passing an argument from the Asterisk dialplan. This allows for easy A/B testing.

**`extensions_custom.conf` Example:**
```
[ai-testing]
; Dial 1001 for Deepgram
exten => 1001,1,Stasis(ai-voice-agent,deepgram)

; Dial 1002 for the Local AI
exten => 1002,1,Stasis(ai-voice-agent,local)
```

---

## 7. Implementation Phases

### 7.1 Phase 0: Proof of Concept (Completed)
- [x] **Deepgram Voice Agent Integration**: Established a working end-to-end call flow with Deepgram's all-in-one service.
- [x] **Core ARI and RTP Handling**: Developed the initial logic for connecting to Asterisk and handling real-time audio.

### 7.2 Phase 1: Core Architecture Refactor (Current)
- [ ] **Implement Provider Interface**: Create the `AIProviderInterface` abstract class in `src/providers/base.py`.
- [ ] **Refactor Deepgram Provider**: Move the existing Deepgram POC code into a modular `src/providers/deepgram.py` that implements the new interface.
- [ ] **Build Core Engine**: Develop `src/engine.py` to handle call orchestration and dynamic provider loading based on dialplan arguments.
- [ ] **Update Dockerfile**: Implement a multi-stage build and configure model mounting via volumes.
- [ ] **Enhance Config System**: Update the configuration manager to support the new YAML structure with multiple providers.

### 7.3 Phase 2: Local AI Provider (Next)
- [ ] **Integrate Vosk, Llama, and Piper**: Build the `LocalAIProvider` in `src/providers/local.py`.
- [ ] **Enhance `install.sh`**: Add the logic to download and manage local model files in the `./models` directory.

---

## 8. Technical Requirements

### 8.1 System Requirements
- **OS**: CentOS 7+, Ubuntu 18.04+
- **Docker**: 20.10+
- **Python**: 3.9+
- **RAM**: 4GB minimum, 8GB recommended
- **CPU**: 2 cores minimum, 4 cores recommended
- **Storage**: 10GB for local models

### 8.2 Asterisk Requirements
- **Version**: Asterisk 16+ or FreePBX 15+
- **ARI**: Enabled and configured
- **Stasis**: Application support
- **RTP**: Native RTP handling

### 8.3 Dependencies
- **Local Models**: Vosk, Llama-cpp-python, Piper
- **Cloud APIs**: Deepgram, OpenAI
- **Python Libraries**: aiohttp, asyncio, pydantic
- **Audio Processing**: librosa, soundfile

---

## 9. Quality Assurance

### 9.1 Testing Strategy
- **Unit Tests**: Individual component testing
- **Integration Tests**: ARI connection and call flow
- **End-to-End Tests**: Complete conversation scenarios
- **Performance Tests**: Response time and resource usage
- **Error Handling Tests**: Failure scenarios and recovery

### 9.2 Performance Targets
- **Response Time**: < 2 seconds for AI responses
- **Audio Latency**: < 500ms for real-time processing
- **Memory Usage**: < 2GB for local models
- **CPU Usage**: < 80% under normal load
- **Uptime**: 99.5% availability

---

## 10. Deployment and Maintenance

### 10.1 Deployment Process
1. **System Check**: Verify requirements and Asterisk status
2. **Configuration**: Interactive setup wizard
3. **Build**: Generate appropriate Docker image
4. **Deploy**: Start container and verify connection
5. **Test**: End-to-end call testing
6. **Monitor**: Status dashboard and logging

### 10.2 Maintenance
- **Logging**: Comprehensive logging for troubleshooting
- **Monitoring**: Health checks and status reporting
- **Updates**: Manual update process (future enhancement)
- **Backup**: Configuration backup and restore

---

## 11. Future Enhancements

### 11.1 Phase 2 Features
- **Multi-language Support**: Additional language models
- **Advanced Customization**: More voice options and personalities
- **Analytics Dashboard**: Call metrics and conversation insights
- **API Integration**: CRM and business system integration

### 11.2 Scalability Options
- **Horizontal Scaling**: Multiple container instances
- **Load Balancing**: Distributed call handling
- **High Availability**: Redundancy and failover
- **Cloud Deployment**: Kubernetes and cloud-native options

---

## 12. Success Criteria

### 12.1 MVP Success Metrics
- [ ] Successful deployment in < 10 minutes
- [ ] Clear, natural conversation quality
- [ ] Reliable call handling and audio playback
- [ ] Easy customization for different businesses
- [ ] Stable operation for 24+ hours

### 12.2 User Acceptance Criteria
- [ ] Asterisk administrators can deploy without external help
- [ ] Business owners can customize greetings and roles
- [ ] System handles common call scenarios reliably
- [ ] Error messages are clear and actionable
- [ ] Documentation is comprehensive and helpful

---

## 13. Risk Assessment

### 13.1 Technical Risks
- **ARI Audio Streaming**: May require additional research
- **Local Model Performance**: CPU requirements for real-time processing
- **Audio Quality**: Ensuring clear, natural speech output
- **Integration Complexity**: Asterisk version compatibility

### 13.2 Mitigation Strategies
- **Prototype Early**: Test ARI audio streaming early
- **Performance Testing**: Benchmark local models thoroughly
- **Fallback Options**: Cloud services as backup
- **Version Testing**: Test with multiple Asterisk versions

---

## 14. Conclusion

The Asterisk AI Voice Agent v3.0 represents a significant simplification and improvement over previous versions. By focusing on a single-container architecture with modular AI engines, we can deliver a solution that is:

- **Easy to Deploy**: One-command installation
- **Easy to Maintain**: Single container, clear configuration
- **Easy to Customize**: Business-specific greetings and roles
- **Easy to Scale**: Modular design allows for future enhancements

This approach addresses the real needs of Asterisk administrators while providing the flexibility and quality required for business use cases.

---

**Document Status**: Draft
**Next Review**: After technical architecture validation
**Approval Required**: Project stakeholders
