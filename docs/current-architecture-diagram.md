# Current Architecture Diagram - ExternalMedia + RTP

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           HOST MACHINE (voiprnd.nemtclouddispatch.com)        │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        DOCKER HOST NETWORKING                          │   │
│  │                                                                         │   │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐     │   │
│  │  │   ASTERISK      │    │   AI-ENGINE     │    │ LOCAL-AI-SERVER │     │   │
│  │  │   Container     │    │   Container     │    │   Container     │     │   │
│  │  │                 │    │                 │    │                 │     │   │
│  │  │ Port: 8088      │    │ Port: 15000     │    │ Port: 8765      │     │   │
│  │  │ (ARI HTTP/WS)   │    │ (Health API)    │    │ (WebSocket)     │     │   │
│  │  │                 │    │                 │    │                 │     │   │
│  │  │ Port: 5060      │    │ Port: 18080     │    │                 │     │   │
│  │  │ (SIP)           │    │ (RTP Server)    │    │                 │     │   │
│  │  │                 │    │                 │    │                 │     │   │
│  │  │ Port: 10000-    │    │                 │    │                 │     │   │
│  │  │ 20000 (RTP)     │    │                 │    │                 │     │   │
│  │  └─────────────────┘    └─────────────────┘    └─────────────────┘     │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        SHARED STORAGE                                  │   │
│  │                                                                         │   │
│  │  /mnt/asterisk_media/ai-generated/  (tmpfs - RAM disk)                 │   │
│  │  /var/lib/asterisk/sounds/          (Asterisk sounds)                  │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Network Configuration

### Docker Networking
- **Mode**: `network_mode: "host"` for all containers
- **Result**: All containers share the host's network namespace
- **IP Addresses**: All containers use `127.0.0.1` (localhost) for inter-container communication

### Port Assignments

| Service | Port | Protocol | Purpose |
|---------|------|----------|---------|
| Asterisk | 8088 | HTTP/WS | ARI (Asterisk REST Interface) |
| Asterisk | 5060 | UDP | SIP signaling |
| Asterisk | 10000-20000 | UDP | RTP audio (dynamic) |
| AI Engine | 15000 | HTTP | Health endpoint |
| AI Engine | 18080 | UDP | RTP server (ExternalMedia) |
| Local AI Server | 8765 | WS | WebSocket for AI processing |

## Current Call Flow

### 1. Call Initiation
```
SIP Caller → Asterisk (127.0.0.1:5060) → Stasis Application
```

### 2. ARI Communication
```
AI Engine ←→ Asterisk (127.0.0.1:8088)
- WebSocket: ws://127.0.0.1:8088/ari/events
- HTTP: http://127.0.0.1:8088/ari/
```

### 3. ExternalMedia Channel Creation
```
AI Engine creates ExternalMedia channel:
- Target: 127.0.0.1:18080
- Codec: ulaw (PCMU)
- Direction: both (sendrecv)
```

### 4. RTP Audio Flow (CURRENT ISSUE)
```
Asterisk RTP → 127.0.0.1:18080 → AI Engine RTP Server
❌ NO PACKETS RECEIVED
```

### 5. AI Processing
```
AI Engine ←→ Local AI Server (127.0.0.1:8765)
- WebSocket connection
- STT, LLM, TTS processing
```

### 6. Audio Playback
```
AI Engine → /mnt/asterisk_media/ai-generated/ → Asterisk → Caller
✅ WORKING - Clean audio confirmed by user
```

## Configuration Details

### AI Engine Configuration
```yaml
external_media:
  rtp_host: "0.0.0.0"        # Bind to all interfaces
  rtp_port: 18080            # Fixed RTP port
  codec: "ulaw"              # PCMU codec
  direction: "both"          # Bidirectional
```

### Docker Compose
```yaml
services:
  ai-engine:
    network_mode: "host"
    volumes:
      - /mnt/asterisk_media:/mnt/asterisk_media
      - /var/lib/asterisk/sounds:/var/lib/asterisk/sounds
  
  local-ai-server:
    network_mode: "host"
    volumes:
      - ./models:/app/models
```

## Current Status

### ✅ Working Components
1. **Call Initiation**: SIP → Asterisk → Stasis
2. **ARI Communication**: AI Engine ↔ Asterisk
3. **ExternalMedia Creation**: Channel created successfully
4. **Bridge Management**: Channels added to bridge
5. **TTS Generation**: Local AI Server processing
6. **Audio Playback**: Clean greeting audio confirmed

### ❌ Broken Components
1. **RTP Audio Reception**: No packets received at 127.0.0.1:18080
2. **Voice Capture**: No audio captured from caller
3. **STT Processing**: No speech-to-text due to no audio

## Root Cause Analysis

### The Problem
- **Expected**: Asterisk sends RTP to 127.0.0.1:18080
- **Reality**: No RTP packets received by AI Engine
- **Architect's Diagnosis**: Network namespace issue (but we use host networking)

### Possible Causes
1. **RTP Server Not Listening**: Port 18080 not bound
2. **Firewall Blocking**: Port 18080 blocked
3. **Asterisk RTP Config**: Asterisk not configured to send RTP
4. **Codec Issues**: PCMU/ulaw codec problems
5. **Timing Issues**: RTP sent before server ready

## Next Steps (Per Architect's Recommendations)

### 1. Verify RTP Server Binding
```bash
# Check if port 18080 is listening
netstat -tulpn | grep 18080
```

### 2. Test Network Connectivity
```bash
# From Asterisk container, test UDP connectivity
nc -u 127.0.0.1 18080
```

### 3. Monitor RTP Traffic
```bash
# Monitor UDP traffic on port 18080
tcpdump -ni any udp port 18080
```

### 4. Add Debug Logging
- Add RTP packet reception logging
- Add SSRC mapping debug logs
- Add frame processing counters

## Success Criteria

### When Fixed, We Should See:
1. **Asterisk Logs**: `UnicastRTP/127.0.0.1:18080-...` channel created
2. **AI Engine Logs**: 
   - "New RTP session created ... ssrc=... addr=(AsteriskIP, AsteriskPort)"
   - "SSRC mapped to caller on first packet"
   - "RTP audio sent to provider ... bytes=3200"
3. **Local AI Server Logs**: Speech processing and responses
4. **User Experience**: Two-way conversation working

## Architecture Benefits

### Current Approach Advantages
1. **Host Networking**: Simple, no Docker networking complexity
2. **ExternalMedia**: Native Asterisk RTP handling
3. **File-based Playback**: Reliable, no streaming complexity
4. **Modular Design**: AI Engine + Local AI Server separation

### Why This Should Work
1. **Network Namespace**: Host networking means 127.0.0.1 is shared
2. **Port Binding**: 0.0.0.0:18080 should receive packets from 127.0.0.1
3. **Codec Match**: ulaw/PCMU is standard and supported
4. **Timing**: RTP server starts before ExternalMedia creation

The architecture is sound - the issue is likely in the RTP packet routing or server binding.
