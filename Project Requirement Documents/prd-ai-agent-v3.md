# Asterisk AI Voice Agent v3.0 - Simplified Architecture
## Product Requirements Document

**Version:** 3.0
**Date:** September 9, 2025
**Status:** Draft
**Target Release:** MVP

---

## 1. Executive Summary

### 1.1 Project Overview
The Asterisk AI Voice Agent v3.0 is a simplified, single-container conversational AI system designed specifically for Asterisk administrators and FreePBX users. The system provides natural, high-quality voice conversations through a streamlined architecture that prioritizes ease of deployment, maintenance, and customization.

### 1.2 Key Value Propositions
- **One-Command Deployment**: Complete setup with a single `./install.sh` command
- **Self-Contained**: No external cloud dependencies for core functionality
- **Business-Ready**: Customizable greetings, roles, and voice personalities
- **Asterisk-Native**: Deep integration with existing Asterisk infrastructure
- **Cost-Effective**: Local AI models eliminate recurring API costs

### 1.3 Success Metrics
- **Deployment Time**: < 10 minutes from clone to working system
- **Uptime**: 99.5% availability
- **Response Time**: < 2 seconds for AI responses
- **Audio Quality**: Clear, natural-sounding speech
- **User Satisfaction**: Easy customization for different business needs

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

### 3.4 AI Engine Options
- **Local Mode**: Fully offline operation with local AI models
- **Cloud Mode**: High-quality cloud-based AI services
- **Hybrid Mode**: Mix of local and cloud services for optimal performance

---

## 4. Technical Architecture

### 4.1 High-Level Architecture
`
┌─────────────────────────────────────────────────────────────┐
│                    Asterisk Server                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │   ARI API   │  │  Stasis App │  │    RTP Engine       │ │
│  │   (Port     │  │  (Custom    │  │   (Native)          │ │
│  │    8088)    │  │   Name)     │  │                     │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ ARI WebSocket + HTTP
                              │
┌─────────────────────────────────────────────────────────────┐
│                AI Voice Agent Container                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │   ARI       │  │    AI       │  │   Configuration     │ │
│  │  Client     │  │  Pipeline   │  │    Manager          │ │
│  │             │  │             │  │                     │ │
│  │ • Call      │  │ • STT       │  │ • Engine Selection  │ │
│  │   Control   │  │ • LLM       │  │ • Voice Settings    │ │
│  │ • Audio     │  │ • TTS       │  │ • Business Rules    │ │
│  │   Playback  │  │             │  │                     │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
`

### 4.2 Container Architecture
- **Single Docker Container**: All AI engines and logic in one container
- **Modular AI Pipeline**: Pluggable STT, LLM, and TTS components
- **Configuration-Driven**: Easy switching between different AI engines
- **Resource Optimized**: Efficient CPU usage for local models

### 4.3 AI Engine Options

#### 4.3.1 Local AI Stack
- **STT**: Vosk (offline, CPU-optimized)
- **LLM**: Llama-cpp-python with 7B-13B parameter models
- **TTS**: Piper TTS (neural, high-quality)
- **Voice Options**:
  - Male: "en_US-lessac-medium" (Professional, clear)
  - Female: "en_US-lessac-high" (Friendly, warm)

#### 4.3.2 Cloud AI Stack
- **STT**: Deepgram (real-time, high accuracy)
- **LLM**: OpenAI GPT-4o (advanced reasoning)
- **TTS**: OpenAI TTS (natural, expressive)
- **Voice Options**: Alloy (neutral), Nova (female), Echo (male)

#### 4.3.3 Hybrid AI Stack
- **STT**: Local Vosk + Cloud Deepgram fallback
- **LLM**: Local Llama + Cloud OpenAI fallback
- **TTS**: Local Piper + Cloud OpenAI fallback
- **Intelligent Fallback**: Automatic switching based on performance

### 4.4 Asterisk Integration
- **ARI WebSocket**: Real-time event handling
- **ARI HTTP API**: Call control and media playback
- **Stasis Application**: Custom application name (configurable)
- **RTP Handling**: Native Asterisk RTP (no external media proxy)

---

## 5. User Experience

### 5.1 Installation Flow
`bash
# Step 1: Clone Repository
git clone https://github.com/your-repo/asterisk-ai-voice-agent
cd asterisk-ai-voice-agent

# Step 2: Run Installation
./install.sh

# What happens:
# 1. System Requirements Check
# 2. Asterisk Status Verification
# 3. Port Availability Check
# 4. AI Engine Selection
# 5. Voice and Personality Setup
# 6. Container Build and Deployment
# 7. Integration Testing
# 8. Status Dashboard
`

### 5.2 Interactive Setup Wizard
`
┌─────────────────────────────────────────────────────────────┐
│              Asterisk AI Voice Agent Setup                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ✓ System Requirements Check                               │
│  ✓ Asterisk Status: Running (v18.5.0)                     │
│  ✓ Port 8088: Available                                    │
│                                                             │
│  AI Engine Selection:                                       │
│  [1] Local Mode (Offline, No API costs)                    │
│  [2] Cloud Mode (High Quality, API costs)                  │
│  [3] Hybrid Mode (Best of both)                            │
│                                                             │
│  Voice Selection:                                           │
│  [1] Male Voice (Professional)                             │
│  [2] Female Voice (Friendly)                               │
│                                                             │
│  Business Configuration:                                    │
│  Company Name: [Jugaar LLC                    ]            │
│  AI Role: [Customer Service Assistant        ]            │
│  Greeting: [Hello, I'm an AI assistant...    ]            │
│                                                             │
│  Asterisk Configuration:                                    │
│  ARI Username: [AIAgent                    ]               │
│  ARI Password: [****************            ]               │
│  Stasis App Name: [ai-voice-agent          ]               │
│                                                             │
│  [Continue] [Back] [Exit]                                   │
└─────────────────────────────────────────────────────────────┘
`

### 5.3 Error Handling
- **Clear Error Messages**: Specific, actionable error descriptions
- **Next Steps Guidance**: Step-by-step resolution instructions
- **Diagnostic Mode**: `./install.sh --diagnose` for troubleshooting
- **Rollback Capability**: Easy cleanup and restart

---

## 6. Configuration Management

### 6.1 Configuration File Structure
`yaml
# config/ai-agent.yaml
asterisk:
  host: "voiprnd.nemtclouddispatch.com"
  port: 8088
  username: "AIAgent"
  password: "c4d5359e2f9ddd394cd6aa116c1c6a96"
  stasis_app: "ai-voice-agent"

ai_engine:
  mode: "local"  # local, cloud, hybrid
  stt:
    provider: "vosk"  # vosk, deepgram
    model: "vosk-model-en-us-0.22"
  llm:
    provider: "llama"  # llama, openai
    model: "llama-2-7b-chat"
    temperature: 0.8
  tts:
    provider: "piper"  # piper, openai
    voice: "en_US-lessac-medium"  # male
    # voice: "en_US-lessac-high"  # female

business:
  company_name: "Jugaar LLC"
  ai_role: "Customer Service Assistant"
  greeting: "Hello, I'm an AI assistant for Jugaar LLC. How can I help you today?"
  escalation_keyword: "agent"
  max_conversation_turns: 10

voice:
  gender: "male"  # male, female
  speed: 1.0
  pitch: 1.0
`

### 6.2 AI Engine Flavors
- **local.yaml**: Fully offline configuration
- **cloud.yaml**: Cloud-based services
- **hybrid.yaml**: Mixed local/cloud approach
- **custom.yaml**: User-defined configuration

---

## 7. Implementation Phases

### 7.1 Phase 1: Core Infrastructure (Week 1-2)
- [ ] Single container architecture
- [ ] ARI client implementation
- [ ] Basic call handling (answer, hangup)
- [ ] Audio playback functionality
- [ ] Configuration management system

### 7.2 Phase 2: AI Pipeline (Week 3-4)
- [ ] Vosk STT integration
- [ ] Local LLM integration (llama-cpp-python)
- [ ] Piper TTS integration
- [ ] Audio streaming from ARI
- [ ] Basic conversation flow

### 7.3 Phase 3: Cloud Integration (Week 5-6)
- [ ] Deepgram STT integration
- [ ] OpenAI LLM integration
- [ ] OpenAI TTS integration
- [ ] Hybrid mode implementation
- [ ] Fallback mechanisms

### 7.4 Phase 4: User Experience (Week 7-8)
- [ ] Installation script
- [ ] Interactive setup wizard
- [ ] Error handling and diagnostics
- [ ] Documentation and examples
- [ ] Testing and validation

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
