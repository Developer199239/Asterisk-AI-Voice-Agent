<context>
## Overview
An open-source AI Voice Agent that integrates with Asterisk/FreePBX using SIP/RTP technology (Asterisk 16+) and answers calls using configurable AI providers. Designed for small and medium businesses across all expertise levels, with a simple Docker-based deployment and CLI-driven configuration.

## Core Features
- **Dual Integration Modes**: SIP/RTP (primary) + AudioSocket (future enhancement) for maximum compatibility
- **Advanced Audio Processing**: Voice Activity Detection (VAD), noise suppression, echo cancellation
- **Multi-provider AI support**: OpenAI Realtime API (MVP), Azure Speech, Deepgram; Future: local via Ollama
- **Real-time Communication**: WebSocket-based AI provider integration for sub-second response times
- **Multi-language conversations**: Auto-detect/switch with provider-dependent capabilities
- **Single, consistent voice per engine instance**: Provider-specific voice configuration
- **User-defined prompts/instructions**: Per-call session context with MCP tool integrations
- **Comprehensive Monitoring**: Health checks, metrics, and structured logging
- **Security & Compliance**: Built-in encryption, access controls, and privacy controls
- **CLI-driven configuration**: Simple setup with validation and help system

## User Experience
- Clone → configure → run → register extension in FreePBX → route calls → AI answers
- **Enhanced Setup**: <5 minute configuration with automatic validation
- **Comprehensive Documentation**: Step-by-step guides, examples, and troubleshooting
- **Production Ready**: Built-in monitoring, security, and scaling capabilities
</context>

<PRD>
## Technical Architecture

### System Components
- **Integration Layer**: AudioSocket (primary) + SIP Client (fallback) for maximum compatibility
- **Audio Processing Engine**: VAD, noise suppression, echo cancellation, codec handling
- **Real-time Communication**: WebSocket connections to AI providers for low-latency responses
- **AI Engine Core**: Conversation loop, context management, provider selection, tool calling
- **Provider Integrations**: OpenAI Realtime API (MVP), Azure Speech, Deepgram; future: Ollama (local)
- **MCP Integration**: Optional tool layer exposed to AI (generic, pluggable)
- **Configuration Manager**: JSON + environment variables with validation and hot-reload
- **Monitoring & Health**: Comprehensive metrics, alerting, and structured logging
- **Security Layer**: Encryption, authentication, access controls, and compliance features

### Integration Modes

#### Primary Mode: SIP/RTP Integration
- **Asterisk Version**: 16+ (minimum requirement)
- **Benefits**: Maximum compatibility, proven technology, extensive documentation
- **Implementation**: Direct SIP registration and RTP audio handling
- **Use Case**: Primary integration mode for all Asterisk 16+ installations

#### Future Enhancement: AudioSocket Integration
- **Asterisk Version**: 18+ (future enhancement)
- **Benefits**: Simplified integration, better performance, native Asterisk support
- **Implementation**: Direct audio streaming via Asterisk's AudioSocket module
- **Use Case**: Future enhancement for Asterisk 18+ installations

### High-Level Flow

#### SIP/RTP Mode (Primary)
1) Admin creates a PJSIP extension in FreePBX/Asterisk 16+
2) Engine container starts and registers to that extension
3) Calls routed to the extension are answered by the engine
4) Audio flows via RTP; engine performs STT → LLM → TTS via chosen provider
5) Conversation continues with per-call context; call ends on BYE or timeout

#### AudioSocket Mode (Future Enhancement)
1) Admin creates a PJSIP extension in FreePBX/Asterisk 18+
2) Engine container starts and connects via AudioSocket
3) Calls routed to the extension are handled by AudioSocket
4) Audio streams directly to AI engine via WebSocket
5) Real-time STT → LLM → TTS processing with sub-second latency
6) Conversation continues with per-call context; call ends on timeout or user action

### Data Models
- **Configuration**: Integration mode, SIP creds, provider settings, audio processing options, security settings
- **Call Session**: call-id, caller-id, language, conversation context, timestamps, audio quality metrics
- **Logs**: Integration events, provider calls, transcripts (optional), errors, security events
- **Metrics**: Response times, audio quality, error rates, system performance

### APIs & Protocols
- **SIP (RFC 3261)**: REGISTER, INVITE/200/ACK, BYE; Digest auth (primary mode)
- **RTP**: Audio streams; codec negotiation via SDP (primary mode)
- **AudioSocket**: Real-time audio streaming (Asterisk 18+ future enhancement)
- **WebSocket**: Real-time communication with AI providers
- **Provider APIs**: OpenAI Realtime API, Azure Speech, Deepgram
- **MCP**: Generic tool invocation if enabled
- **Health/Monitoring**: HTTP endpoints for health checks and metrics

### Infrastructure
- **Docker Container**: Multi-stage builds, optimized for voice processing
- **Networking**: Host networking for SIP/RTP, configurable for AudioSocket
- **Asterisk Compatibility**: 16+ (SIP/RTP primary), 18+ (AudioSocket future enhancement)
- **Storage**: Filesystem logs, optional database for metrics
- **Security**: TLS encryption, access controls, audit logging

## Enhanced Core Features

### Audio Processing
- **Voice Activity Detection (VAD)**: Natural interruption handling and conversation flow
- **Noise Suppression**: AI-powered background noise cancellation
- **Echo Cancellation**: Clear audio quality in various environments
- **Codec Support**: G.711 µ-law/A-law, G.722, with automatic negotiation
- **Audio Quality Monitoring**: Real-time quality metrics and optimization

### Real-time Communication
- **WebSocket Integration**: Low-latency communication with AI providers
- **Connection Pooling**: Efficient WebSocket management and failover
- **Latency Optimization**: Sub-second response times for natural conversations
- **Quality Metrics**: Audio quality monitoring and automatic optimization

### Security & Compliance
- **Data Encryption**: End-to-end encryption for voice data
- **Privacy Controls**: Configurable data retention and anonymization
- **Compliance**: GDPR, HIPAA, CCPA support with built-in controls
- **Access Control**: Role-based permissions and authentication
- **Audit Logging**: Comprehensive security event logging

### Monitoring & Health
- **Health Endpoints**: Readiness and liveness checks for orchestration
- **Metrics Collection**: Performance, quality, and error metrics
- **Alerting**: Configurable alerts for system issues
- **Dashboards**: Optional Grafana integration for visualization

## Development Roadmap

### MVP (Phase 1)
- **SIP/RTP Integration**: Primary integration mode with Asterisk 16+
- **Basic Audio Processing**: VAD and essential audio handling
- **OpenAI Realtime API**: WebSocket-based real-time communication
- **Configuration System**: JSON + env vars with validation
- **Basic Security**: Essential encryption and access controls
- **Health Monitoring**: Basic health checks and logging
- **CLI Tools**: Configuration validation and help system

### Phase 2
- **Advanced Audio Processing**: Noise suppression, echo cancellation
- **Multiple Provider Support**: Azure Speech, Deepgram with fallback
- **MCP Tool Integrations**: Calendar, web automation with safe defaults
- **Enhanced Security**: Comprehensive compliance and audit features
- **Monitoring Dashboard**: Optional web-based monitoring interface
- **Performance Optimization**: Latency reduction and quality improvements

### Phase 3
- **AudioSocket Integration**: Future enhancement for Asterisk 18+
- **Local Model Support**: Ollama integration for on-premises deployment
- **Multi-instance Scaling**: Load balancing and horizontal scaling
- **Web UI**: Optional configuration and management interface
- **Advanced Analytics**: Call analytics and business intelligence
- **Enterprise Features**: Advanced security, compliance, and support

## Logical Dependency Chain
1) **Integration Layer** (SIP/RTP primary + AudioSocket future) → 2) **Audio Processing** (VAD, noise suppression) → 3) **Configuration System** → 4) **Real-time Communication** (WebSocket) → 5) **AI Provider Integration** → 6) **Call Loop & Session Management** → 7) **Security & Compliance** → 8) **Monitoring & Health** → 9) **Additional Providers** → 10) **MCP Tools** → 11) **AudioSocket Enhancement** → 12) **Local Models**

## Risks and Mitigations

### Technical Risks
- **SIP/RTP Protocol Complexity**: Protocol compliance and audio quality → **Mitigation**: Use proven libraries, extensive testing
- **WebSocket Complexity**: Real-time connection management → **Mitigation**: Connection pooling and failover
- **Audio Processing Overhead**: CPU-intensive operations → **Mitigation**: Hardware requirements and optimization
- **Integration Complexity**: Multiple integration modes → **Mitigation**: Clear documentation and examples

### Security Risks
- **Voice Data Privacy**: Sensitive voice data handling → **Mitigation**: Encryption and compliance controls
- **API Security**: AI provider API security → **Mitigation**: Secure authentication and monitoring
- **Network Security**: Voice data transmission → **Mitigation**: TLS encryption and access controls

### Operational Risks
- **Provider Reliability**: AI provider availability → **Mitigation**: Multiple providers with fallback
- **Configuration Errors**: User setup mistakes → **Mitigation**: Validation and clear documentation
- **Performance Issues**: Latency and quality problems → **Mitigation**: Monitoring and optimization

## Appendix

### Code Reuse From Existing Project
[Original repo at https://github.com/OpenSIPS/opensips-ai-voice-connector-ce/tree/main/src]
- `docker-setup/engine/src/config.py`: Configuration loading patterns (adapt to JSON + env)
- `docker-setup/engine/src/engine.py`: Conversation loop and provider selection logic
- `docker-setup/engine/src/call.py`: Call/session state management patterns
- `docker-setup/engine/src/utils.py`: Parsing helpers and logging patterns
- `docker-setup/engine/src/openai_api.py`, `azure_api.py`, `deepgram_api.py`: Provider request/response patterns
- `docker-setup/engine/src/rtp.py`, `codec.py`, `opus.py`: Audio handling references

### New Components To Build

#### Integration Layer
- **AudioSocket Client**: `src/audiosocket_client.py` (primary integration)
- **SIP Client**: `src/sip_client.py` (fallback integration)
- **Integration Manager**: `src/integration_manager.py` (mode selection and fallback)

#### Audio Processing
- **Audio Processor**: `src/audio_processor.py` (VAD, noise suppression, echo cancellation)
- **Codec Handler**: `src/codec_handler.py` (G.711, G.722 support)
- **Audio Quality Monitor**: `src/audio_quality.py` (quality metrics and optimization)

#### Real-time Communication
- **WebSocket Manager**: `src/websocket_manager.py` (AI provider connections)
- **Connection Pool**: `src/connection_pool.py` (efficient connection management)

#### AI Integration
- **Provider Interface**: `src/providers/base.py` (unified provider interface)
- **OpenAI Realtime**: `src/providers/openai_realtime.py` (WebSocket-based integration)
- **Azure Speech**: `src/providers/azure_speech.py` (Azure integration)
- **Deepgram**: `src/providers/deepgram.py` (Deepgram integration)

#### Security & Compliance
- **Security Manager**: `src/security/security_manager.py` (encryption, access control)
- **Compliance Handler**: `src/security/compliance.py` (GDPR, HIPAA, CCPA)
- **Audit Logger**: `src/security/audit.py` (security event logging)

#### Monitoring & Health
- **Health Monitor**: `src/monitoring/health.py` (health checks and metrics)
- **Metrics Collector**: `src/monitoring/metrics.py` (performance and quality metrics)
- **Alert Manager**: `src/monitoring/alerts.py` (alerting and notifications)

#### Configuration & Management
- **Config Schema**: `config/engine.json` + `src/config_schema.py` (validation and defaults)
- **CLI Interface**: `src/cli.py` (configuration and management tools)
- **MCP Integration**: `src/mcp_client.py` (optional tool integrations)

### Configuration (Enhanced)

#### Required Environment Variables
- `INTEGRATION_MODE`: `sip` or `audiosocket` (default: `sip`)
- `ASTERISK_HOST`: Asterisk server hostname/IP
- `ASTERISK_VERSION`: Asterisk version (16+ for SIP, 18+ for AudioSocket)
- `PROVIDER`: AI provider (`openai`, `azure`, `deepgram`)
- Provider API keys: `OPENAI_API_KEY`, `AZURE_SPEECH_KEY`, `DEEPGRAM_API_KEY`

#### SIP Mode Variables (Primary)
- `SIP_EXTENSION`: PJSIP extension number
- `SIP_PASSWORD`: Extension password
- `SIP_DOMAIN`: SIP domain (optional)

#### Audio Processing Variables
- `VAD_ENABLED`: Enable voice activity detection (default: `true`)
- `NOISE_SUPPRESSION`: Enable noise suppression (default: `true`)
- `ECHO_CANCELLATION`: Enable echo cancellation (default: `true`)
- `AUDIO_QUALITY_MONITORING`: Enable quality monitoring (default: `true`)

#### Security Variables
- `ENCRYPTION_ENABLED`: Enable data encryption (default: `true`)
- `AUDIT_LOGGING`: Enable audit logging (default: `true`)
- `DATA_RETENTION_DAYS`: Data retention period (default: `30`)

#### Optional Variables
- `VOICE`: Provider-specific voice selection
- `PROMPT`: System prompt for AI
- `INSTRUCTIONS`: Additional instructions
- `TRANSCRIPTION_ENABLED`: Enable call transcription (default: `false`)
- `LOG_LEVEL`: Logging level (`debug`, `info`, `warn`, `error`)
- `MONITORING_ENABLED`: Enable monitoring (default: `true`)

### Setup Steps (Enhanced)

#### SIP Mode (Primary)
1) **Verify Asterisk Version**: Ensure Asterisk 16+ is installed
2) **Create PJSIP Extension**: Create extension in FreePBX/Asterisk
3) **Clone and Configure**: Clone repo, copy example config, set environment variables
4) **Start Container**: Run Docker container with SIP integration
5) **Verify Registration**: Check logs for successful SIP registration
6) **Test Call**: Route test call to extension, verify AI response
7) **Monitor Performance**: Check health endpoints and metrics

#### AudioSocket Mode (Future Enhancement)
1) **Verify Asterisk Version**: Ensure Asterisk 18+ is installed
2) **Create PJSIP Extension**: Create extension in FreePBX/Asterisk
3) **Configure AudioSocket**: Enable AudioSocket module in Asterisk
4) **Clone and Configure**: Clone repo, copy example config, set environment variables
5) **Start Container**: Run Docker container with AudioSocket integration
6) **Verify Integration**: Check logs for successful AudioSocket connection
7) **Test Call**: Route test call to extension, verify AI response
8) **Monitor Performance**: Check health endpoints and metrics

### Diagrams

#### SIP/RTP Integration Flow (Primary)
```
Caller → Asterisk/FreePBX → (SIP INVITE) → AI Engine → Provider (STT/LLM/TTS) → AI Engine → (RTP audio) → Asterisk → Caller
```

#### AudioSocket Integration Flow (Future Enhancement)
```
Caller → Asterisk/FreePBX → AudioSocket → AI Engine → WebSocket → AI Provider
                                                      ↓
Caller ← Asterisk/FreePBX ← AudioSocket ← AI Engine ← WebSocket ← AI Provider
```

### Success Criteria (Enhanced)

#### MVP Success Criteria
- **Integration**: Engine registers as SIP extension with Asterisk 16+
- **Call Handling**: Calls are answered by AI with <2s response time
- **Audio Quality**: Clear audio with VAD and noise suppression
- **Provider Integration**: Works with OpenAI Realtime API using defaults
- **Security**: Data encryption and basic access controls
- **Monitoring**: Health checks and basic metrics collection
- **Reliability**: 99%+ uptime with automatic failover

#### Phase 2 Success Criteria
- **Multi-Provider**: Support for Azure Speech and Deepgram with fallback
- **Advanced Audio**: Full noise suppression and echo cancellation
- **MCP Integration**: Working tool integrations with safety controls
- **Enhanced Security**: Full compliance and audit capabilities
- **Monitoring Dashboard**: Optional web-based monitoring interface
- **Performance**: Sub-second response times with quality optimization

#### Production Success Criteria
- **Scalability**: Horizontal scaling with load balancing
- **Security**: Enterprise-grade security and compliance
- **Monitoring**: Comprehensive metrics and alerting
- **Reliability**: 99.9% uptime with automatic recovery
- **Usability**: <5 minute setup with intuitive configuration
- **Performance**: Optimal audio quality and response times

</PRD>
