# Changelog

All notable changes to the Asterisk AI Voice Agent project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.0.0] - 2025-10-29

### 🎉 Major Release: Modular Pipeline Architecture

Version 4.0 introduces a **production-ready modular pipeline architecture** that enables flexible combinations of Speech-to-Text (STT), Large Language Models (LLM), and Text-to-Speech (TTS) providers. This release represents a complete architectural evolution while maintaining backward compatibility with existing deployments.

### Added

#### Core Architecture
- **Modular Pipeline System**: Mix and match STT, LLM, and TTS providers
  - Local STT (Vosk) + Cloud LLM (OpenAI) + Local TTS (Piper)
  - Cloud STT (Deepgram) + Cloud LLM (OpenAI) + Cloud TTS (Deepgram)
  - Fully local pipeline (Vosk + Phi-3/Llama + Piper)
- **Unified Configuration Format**: Single YAML file for all pipeline and provider settings
- **Golden Baseline Configurations**: Three validated, production-ready configurations:
  - **OpenAI Realtime**: Cloud monolithic agent (fastest, <2s response)
  - **Deepgram Voice Agent**: Enterprise cloud agent with Think stage
  - **Local Hybrid**: Privacy-focused with local STT/TTS + cloud LLM

#### Audio Transport
- **Dual Transport Support**: AudioSocket (TCP) and ExternalMedia RTP (UDP)
- **Automatic Transport Selection**: Optimal transport chosen per configuration
- **Enhanced Audio Processing**: Improved resampling, echo cancellation, and codec handling
- **Pipeline Audio Routing**: Fixed audio path for pipeline configurations
- **Transport Compatibility Matrix**: Documented all configuration + transport combinations

#### Monitoring & Observability
- **Production Monitoring Stack**: Prometheus + Grafana with 5 pre-built dashboards
  - System Overview: Active calls, provider distribution
  - Call Quality: Turn latency (p50/p95/p99), processing time
  - Audio Quality: RMS levels, underflows, jitter buffer depth
  - Provider Performance: Provider-specific metrics and health
  - Barge-In Analysis: Interrupt behavior and timing
- **50+ Metrics**: Comprehensive call quality, audio quality, and system health metrics
- **Alert Rules**: Critical and warning alerts for production monitoring
- **Health Endpoint**: `/metrics` endpoint on port 15000 for Prometheus scraping

#### Installation & Setup
- **Interactive Installer**: `install.sh` with guided pipeline selection
  - Choose from 3 golden baseline configurations
  - Automatic dependency setup per configuration
  - Model downloads for local pipelines
  - Environment validation and configuration
- **Two-File Configuration Model**: 
  - `.env` for secrets and credentials (gitignored)
  - `config/ai-agent.yaml` for pipeline definitions (committed)
- **Streamlined User Journey**: From clone to first call in <15 minutes

#### Documentation
- **FreePBX Integration Guide**: Complete v4.0 guide with channel variables
  - `AI_CONTEXT`: Department/call-type specific routing
  - `AI_GREETING`: Per-call greeting customization
  - `AI_PERSONA`: Dynamic persona switching
  - Remote deployment configurations (NFS, Docker, Kubernetes)
  - Network and shared storage setup for distributed deployments
- **Configuration Reference**: Comprehensive YAML parameter documentation
- **Transport Compatibility Guide**: Validated configuration + transport combinations
- **Golden Baseline Case Studies**: Detailed performance analysis and tuning guides
- **Inline YAML Documentation**: Comprehensive comments with ranges and impacts

#### Developer Experience
- **CLI Tools**: Go-based `agent` command with 5 subcommands
  - `agent init`: Interactive setup wizard
  - `agent doctor`: Health diagnostics and validation
  - `agent demo`: Demo call functionality
  - `agent troubleshoot`: Interactive troubleshooting assistant
  - `agent version`: Version and build information
- **Enhanced Logging**: Structured logging with context and call tracking
- **RCA Tools**: Root cause analysis scripts for audio quality debugging
- **Test Infrastructure**: Baseline validation and regression testing
- **IDE Integration**: Full development context preserved in develop branch

### Changed

#### Configuration
- **YAML Structure**: Streamlined provider configuration format
- **Settings Consolidation**: Removed unused/duplicate settings (`llm.model`, `external_media.jitter_buffer_ms`)
- **downstream_mode Enforcement**: Now properly gates streaming vs file playback
- **Security Model**: Credentials **ONLY** in `.env`, never in YAML files

#### Audio Processing
- **VAD Configuration**: Optimized Voice Activity Detection for each provider
  - OpenAI Realtime: `webrtc_aggressiveness: 1` (balanced mode)
  - Server-side VAD support for providers that offer it
- **Barge-In System**: Enhanced interrupt detection with configurable thresholds
- **Audio Routing**: Fixed pipeline audio routing for AudioSocket and RTP transports

#### Performance
- **Response Times**: Validated response times for all golden baselines:
  - OpenAI Realtime: 0.5-1.5s typical
  - Deepgram Hybrid: <3s typical
  - Local Hybrid: 3-7s depending on hardware
- **Echo Cancellation**: Improved echo filtering with SSRC-based detection
- **Jitter Buffer**: Optimized buffer management for streaming playback

### Fixed

- **AudioSocket Pipeline Audio**: Fixed audio routing to STT adapters in pipeline mode
- **RTP Echo Loop**: Added SSRC-based filtering to prevent echo feedback
- **Provider Bytes Tracking**: Corrected audio chunk accounting for accurate pacing
- **Normalizer Consistency**: Fixed audio normalization for consistent output
- **Configuration Loading**: Ensured all config values properly honored at runtime
- **Sample Rate Handling**: Fixed provider-specific sample rate overrides

### Deprecated

- **Legacy YAML Templates**: Replaced with 3 golden baseline configurations
  - `ai-agent.openai-agent.yaml` → `ai-agent.golden-openai.yaml`
  - `ai-agent.deepgram-agent.yaml` → `ai-agent.golden-deepgram.yaml`
  - `ai-agent.hybrid.yaml` → `ai-agent.golden-local-hybrid.yaml`
- **Development Artifacts**: Moved to `archived/` folder (not tracked in git)

### Technical Details

#### System Requirements
- **Minimum**: 4 CPU cores, 8GB RAM (cloud configurations)
- **Recommended**: 8+ CPU cores, 16GB RAM (local pipelines)
- **GPU**: Optional for local-ai-server (improves LLM performance)

#### Compatibility
- **Asterisk**: 18+ required (for AudioSocket support)
- **FreePBX**: 15+ recommended
- **Python**: 3.10+
- **Docker**: 20.10+
- **Docker Compose**: 2.0+

#### Breaking Changes
**None** - This release maintains backward compatibility with existing deployments. Users can continue using existing configurations while adopting new features incrementally.

### Migration Guide

**No migration needed** - This is the first production release. There are no users on v3.0 requiring migration.

For new deployments:
1. Clone repository
2. Run `./install.sh` and select a golden baseline
3. Configure `.env` with your credentials
4. Deploy with `docker compose up -d`
5. Follow the FreePBX Integration Guide to configure Asterisk

### Contributors

- Haider Jarral (@hkjarral) - Architecture, implementation, documentation

### Links

- **Repository**: https://github.com/hkjarral/Asterisk-AI-Voice-Agent
- **Documentation**: [docs/README.md](docs/README.md)
- **FreePBX Guide**: [docs/FreePBX-Integration-Guide.md](docs/FreePBX-Integration-Guide.md)
- **Monitoring**: [monitoring/README.md](monitoring/README.md)

---

## [Unreleased]

### Planned for v4.1
- **Additional Provider Integrations**: Anthropic Claude, Google Gemini
- **Advanced Call Routing**: Transfer capabilities and multi-leg calls
- **WebRTC Support**: SIP client integration
- **High Availability**: Clustering and load balancing
- **Config Cleanup**: Remove deprecated settings (from v3.0)

---

## Version History

- **v4.0.0** (2025-10-29) - Modular pipeline architecture, production monitoring, golden baselines
- **v3.0.0** (2025-09-16) - Modular pipeline architecture, file based playback
- **v2.0.0** - Internal development version (never released)
- **v1.0.0** - Initial concept (never released)

[4.0.0]: https://github.com/hkjarral/Asterisk-AI-Voice-Agent/releases/tag/v4.0.0
[Unreleased]: https://github.com/hkjarral/Asterisk-AI-Voice-Agent/compare/v4.0.0...HEAD
