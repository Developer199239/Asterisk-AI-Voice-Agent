# FreePBX Integration Guide (ExternalMedia Architecture)

**Note:** This document describes the integration of the AI Voice Agent with FreePBX using the ExternalMedia RTP architecture. This provides reliable real-time audio capture and requires minimal dialplan modifications.

## 1. Overview

This guide explains how to integrate the AI Voice Agent with FreePBX using the ExternalMedia RTP architecture. The system provides reliable real-time audio capture through RTP server integration and requires minimal dialplan configuration.

## 2. Prerequisites

-   A working FreePBX installation with Asterisk 16+ or FreePBX 15+
-   Docker and Docker Compose installed on the same server
-   The AI Voice Agent project cloned to a directory (e.g., `/root/Asterisk-AI-Voice-Agent`)
-   Port 18080 available for RTP server connections
-   ARI enabled in Asterisk with appropriate user permissions

## 3. Dialplan Configuration

### Step 3.1: Add Dialplan Contexts

Add the following dialplan contexts to your FreePBX system:

```asterisk
[from-ai-agent]
exten => s,1,NoOp(Handing call directly to Stasis for AI processing)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

[ai-externalmedia]
exten => s,1,NoOp(ExternalMedia + RTP AI Voice Agent)
 same => n,Answer()
 same => n,Wait(1)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

### Step 3.2: Configure Inbound Routes

1. **Log into FreePBX Admin Panel**
2. **Navigate to**: Connectivity → Inbound Routes
3. **Create New Route**:
   - **Description**: AI Voice Agent
   - **DID Number**: Your desired phone number
   - **Set Destination**: Custom Destination
   - **Custom Destination**: `from-ai-agent,s,1`

### Step 3.3: Verify ARI Configuration

Ensure ARI is properly configured in `/etc/asterisk/ari.conf`:

```ini
[general]
enabled = yes
pretty = yes
allowed_origins = 127.0.0.1

[asterisk-ai-voice-agent]
type = user
read_only = no
password = your_ari_password
```

## 4. AI Voice Agent Configuration

### Step 4.1: Environment Setup

Create a `.env` file in the project root:

```bash
# Asterisk Configuration
ASTERISK_HOST=127.0.0.1
ASTERISK_ARI_USERNAME=asterisk-ai-voice-agent
ASTERISK_ARI_PASSWORD=your_ari_password

# AI Provider Configuration (if using cloud providers)
DEEPGRAM_API_KEY=your_deepgram_key
OPENAI_API_KEY=your_openai_key
```

### Step 4.2: Configuration File

Update `config/ai-agent.yaml`:

```yaml
# Application Configuration
default_provider: "local"
audio_transport: "externalmedia"
downstream_mode: "file"

# Asterisk Configuration
asterisk:
  host: "127.0.0.1"
  port: 8088
  username: "asterisk-ai-voice-agent"
  password: "your_ari_password"
  app_name: "asterisk-ai-voice-agent"

# ExternalMedia Configuration
external_media:
  host: "127.0.0.1"
  port: 18080
  codec: "ulaw"

# VAD Configuration
vad:
  webrtc_aggressiveness: 0
  webrtc_start_frames: 3
  webrtc_end_silence_frames: 50
  fallback_interval_ms: 2000
  fallback_buffer_size: 128000

# Provider Configuration
providers:
  local:
    enabled: true
    stt_model: "vosk"
    llm_model: "tinyllama"
    tts_model: "piper"

# LLM Configuration
llm:
  model: "tinyllama"
  max_tokens: 100
  temperature: 0.7
  context_window: 2048
```

## 5. Deployment

### Step 5.1: Start the Services

```bash
# Start both AI Engine and Local AI Server
docker-compose up -d

# Check service status
docker-compose ps

# View logs
docker-compose logs -f ai-engine
docker-compose logs -f local-ai-server
```

### Step 5.2: Verify Health

Check the health endpoint:

```bash
curl http://127.0.0.1:15000/health
```

Expected response:
```json
{
  "status": "healthy",
  "ari_connected": true,
  "rtp_server_running": true,
  "audio_transport": "externalmedia",
  "active_calls": 0,
  "providers": {
    "local": "ready"
  }
}
```

## 6. Testing

### Step 6.1: Test Call

1. **Place a test call** to your configured DID number
2. **Verify call flow**:
   - Call should be answered immediately
   - AI should play greeting: "Hello, how can I help you?"
   - You should be able to speak and get AI responses
   - Call should end normally when you hang up

### Step 6.2: Monitor Logs

```bash
# Monitor AI Engine logs
docker-compose logs -f ai-engine

# Monitor Local AI Server logs
docker-compose logs -f local-ai-server

# Monitor Asterisk logs
tail -f /var/log/asterisk/full
```

## 7. Troubleshooting

### Common Issues

**Call not reaching AI Engine**:
- Check ARI configuration and credentials
- Verify dialplan context is correct
- Check firewall settings for port 8088

**No audio processing**:
- Verify RTP server is running on port 18080
- Check ExternalMedia configuration
- Monitor RTP server logs for connection issues

**Poor STT accuracy**:
- Check audio quality and volume
- Verify VAD configuration
- Consider adjusting fallback buffer size

**Slow LLM responses**:
- This is expected with TinyLlama model
- Consider switching to faster models
- Reduce max_tokens for faster generation

### Debug Commands

```bash
# Check container status
docker-compose ps

# Check RTP server status
netstat -tlnp | grep 18080

# Check ARI connectivity
curl -u asterisk-ai-voice-agent:password http://127.0.0.1:8088/ari/asterisk/info

# Check Asterisk modules
asterisk -rx "module show like externalmedia"
```

## 8. Production Considerations

### Performance Optimization

- **LLM Model**: Consider switching to faster models (Phi-3-mini, Qwen2-0.5B)
- **Buffer Sizes**: Optimize VAD and fallback buffer sizes for your use case
- **Resource Limits**: Set appropriate Docker resource limits
- **Monitoring**: Implement proper logging and monitoring

### Security

- **ARI Credentials**: Use strong passwords and restrict access
- **Network Security**: Consider VPN or firewall rules
- **Container Security**: Keep Docker images updated
- **File Permissions**: Secure configuration files

### Scaling

- **Multiple Calls**: System supports concurrent calls
- **Load Balancing**: Consider multiple AI Engine instances
- **Database**: Add database for call logging and analytics
- **Monitoring**: Implement comprehensive monitoring and alerting

## 9. Support

For issues and support:

1. **Check Logs**: Always check container and Asterisk logs first
2. **Health Endpoint**: Use `/health` endpoint to verify system status
3. **Configuration**: Verify all configuration files are correct
4. **Documentation**: Review this guide and main project documentation

## 10. Conclusion

The ExternalMedia RTP architecture provides a robust, production-ready solution for AI voice agents with FreePBX. The minimal dialplan configuration makes it easy to integrate while the RTP server provides reliable audio processing.

The system is now fully functional with:
- ✅ Real-time audio capture via RTP server
- ✅ Accurate STT processing with Vosk
- ✅ Natural LLM responses with TinyLlama
- ✅ High-quality TTS with Piper
- ✅ Complete conversation flow
- ✅ Production-ready architecture