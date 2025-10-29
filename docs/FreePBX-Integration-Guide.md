# FreePBX Integration Guide

Complete guide for integrating Asterisk AI Voice Agent v4.0 with FreePBX.

## 1. Overview

The Asterisk AI Voice Agent v4.0 integrates with FreePBX using the **Asterisk REST Interface (ARI)**. Calls enter the Stasis application, and the `ai-engine` handles all call control, audio transport, and AI provider orchestration.

**v4.0 supports 3 validated configurations:**
- **OpenAI Realtime** - Cloud-based monolithic agent
- **Deepgram Voice Agent** - Enterprise cloud agent with Think stage
- **Local Hybrid** - Local STT/TTS + Cloud LLM (privacy-focused)

Each configuration uses the optimal transport automatically (AudioSocket or ExternalMedia RTP).

## 2. Prerequisites

### 2.1 System Requirements

**For co-located deployment** (recommended for beginners):
- FreePBX installation with Asterisk 18+ (or FreePBX 15+) and ARI enabled
- Docker and Docker Compose installed on the **same host** as FreePBX
- Repository cloned (e.g., `/root/Asterisk-AI-Voice-Agent`)
- Port **8090/TCP** accessible for AudioSocket connections
- Port **18080/UDP** accessible for ExternalMedia RTP (if using RTP transport)
- Valid `.env` containing ARI credentials and provider API keys

**For remote deployment** (Asterisk on different host/container):
- Network connectivity between ai-engine and Asterisk hosts:
  - **ARI**: TCP port 8088 (Asterisk → ai-engine)
  - **AudioSocket**: TCP port 8090 (Asterisk → ai-engine)
  - **ExternalMedia RTP**: UDP port 18080 (bidirectional)
- **Shared storage** for media files (required for pipeline configurations):
  - NFS mount, Docker volume, or other network filesystem
  - Both Asterisk and ai-engine must access `/mnt/asterisk_media/ai-generated`
- Set `ASTERISK_HOST` in `.env` to Asterisk's IP/hostname (not 127.0.0.1)

**Note**: Remote deployment requires careful network and storage configuration. See section 2.4 below.

### 2.2 Create/Verify ARI User in FreePBX

You must have a non-readonly ARI user for the engine to control calls.

Steps (FreePBX UI):

1. Navigate to: `Settings → Asterisk REST Interface Users`.
2. Click `+ Add User` (or edit an existing one).
3. Set:
   - User Name: e.g., `AIAgent`
   - User Password: a strong password
   - Password Type: `Crypt` or `Plain Text`
   - Read Only: `No`
4. Save Changes and “Apply Config”.

Use these in your `.env`:

```env
ASTERISK_ARI_USERNAME=AIAgent
ASTERISK_ARI_PASSWORD=your-strong-password
```

Snapshot:

![FreePBX ARI User](freepbx/img/snapshot-3-ari-user.png)

### 2.3 Prerequisite Checks

Verify ARI and AudioSocket modules are loaded:

```bash
asterisk -rx "module show like res_ari_applications"
asterisk -rx "module show like app_audiosocket"
```

**Expected output**:

```text
Module                         Description                               Use Count  Status   Support Level
res_ari_applications.so        RESTful API module - Stasis application   0          Running  core
1 modules loaded

Module                         Description                               Use Count  Status   Support Level
app_audiosocket.so             AudioSocket Application                    20         Running  extended
1 modules loaded
```

If your Asterisk is <18, upgrade using:

```bash
asterisk-switch-version   # aka asterisk-version-switch
```

Then select Asterisk 18+.

### 2.4 Remote Deployment Configuration

**When to use**: Asterisk and ai-engine are on different hosts/containers.

#### Network Configuration

Set `ASTERISK_HOST` in your `.env` file to the Asterisk host's IP or hostname:

```env
# For co-located (same host):
ASTERISK_HOST=127.0.0.1

# For remote Asterisk:
ASTERISK_HOST=192.168.1.100          # IP address
# OR
ASTERISK_HOST=asterisk.example.com   # Hostname/FQDN
```

**Required ports** (open firewall between hosts):

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| 8088 | TCP | ai-engine → Asterisk | ARI/WebSocket |
| 8090 | TCP | Asterisk → ai-engine | AudioSocket |
| 18080 | UDP | Bidirectional | ExternalMedia RTP |

#### Shared Storage Configuration

**Why needed**: Pipeline configurations (Local Hybrid) generate audio files that Asterisk must playback.

**Path requirement**: Both systems must access the same files at `/mnt/asterisk_media/ai-generated`

**Solutions**:

**Option 1: NFS Mount** (recommended for bare metal)

```bash
# On ai-engine host:
sudo mkdir -p /mnt/asterisk_media/ai-generated
sudo mount -t nfs asterisk-host:/mnt/asterisk_media/ai-generated /mnt/asterisk_media/ai-generated

# Make permanent in /etc/fstab:
asterisk-host:/mnt/asterisk_media/ai-generated  /mnt/asterisk_media/ai-generated  nfs  defaults  0  0
```

**Option 2: Docker Named Volume** (for containerized Asterisk)

```yaml
# In docker-compose.yml for both Asterisk and ai-engine:
volumes:
  asterisk_media:
    driver: local
    driver_opts:
      type: nfs
      o: addr=nfs-server.example.com,rw
      device: ":/export/asterisk_media"

services:
  asterisk:
    volumes:
      - asterisk_media:/mnt/asterisk_media
  
  ai-engine:
    volumes:
      - asterisk_media:/mnt/asterisk_media
```

**Option 3: Kubernetes Persistent Volume**

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: asterisk-media-pv
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteMany  # Critical: Both pods need write access
  nfs:
    server: nfs-server.example.com
    path: /export/asterisk_media
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: asterisk-media-pvc
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 10Gi
```

**Verification**:

```bash
# On ai-engine host/container:
echo "test" > /mnt/asterisk_media/ai-generated/test.txt

# On Asterisk host/container:
cat /mnt/asterisk_media/ai-generated/test.txt  # Should output: test
```

**Note**: Cloud configurations (OpenAI Realtime, Deepgram) use streaming and **don't require shared storage**.

## 3. Dialplan Configuration

### 3.1 Available Channel Variables

You can customize agent behavior per-call using Asterisk channel variables:

| Variable | Description | Example |
|----------|-------------|---------|  
| `AI_CONTEXT` | Custom context for conversation (e.g., department, call type) | `customer_support`, `sales`, `billing` |
| `AI_GREETING` | Override the default greeting for this call | `"Hello! Welcome to our sales team."` |
| `AI_PERSONA` | Override the AI persona/instructions for this call | `"You are a helpful billing assistant."` |
| `CALLERID(name)` | Caller's name (automatically available to AI if set) | Useful for personalization |
| `CALLERID(num)` | Caller's number (automatically available to AI) | Can be used for lookups |

**Note**: The AI engine reads these variables when the call enters Stasis. Set them **before** calling `Stasis()`.

### 3.2 Edit extensions_custom.conf via FreePBX UI

Use the built‑in editor to add the contexts below.

**Steps:**

1. Navigate to: **Admin → Config Edit**
2. In the left tree, expand **"Asterisk Custom Configuration Files"**
3. Click `extensions_custom.conf`
4. Paste the contexts from the next section, Save, then click **"Apply Config"**

Snapshot:

![Config Edit - extensions_custom.conf](freepbx/img/snapshot-1-config-edit.png)

### 3.3 Basic Dialplan Context (Works for All Configurations)

This simple context works for all 3 golden baselines. The `ai-engine` automatically uses the active configuration from `config/ai-agent.yaml`:

```asterisk
[from-ai-agent]
exten => s,1,NoOp(Asterisk AI Voice Agent v4.0)
 same => n,Answer()
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

**That's it!** This is all you need for basic operation.

### 3.4 Advanced: Context-Specific Routing

For more control, you can set different contexts per department or call type:

```asterisk
; Customer Support context
[from-ai-agent-support]
exten => s,1,NoOp(AI Agent - Customer Support)
 same => n,Answer()
 same => n,Set(AI_CONTEXT=customer_support)
 same => n,Set(AI_PERSONA=You are a helpful customer support agent. Be empathetic and solution-focused.)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

; Sales context
[from-ai-agent-sales]
exten => s,1,NoOp(AI Agent - Sales)
 same => n,Answer()
 same => n,Set(AI_CONTEXT=sales)
 same => n,Set(AI_GREETING=Hello! Thanks for your interest. How can I help you today?)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

; Billing context with caller lookup
[from-ai-agent-billing]
exten => s,1,NoOp(AI Agent - Billing for ${CALLERID(num)})
 same => n,Answer()
 same => n,Set(AI_CONTEXT=billing)
 same => n,Set(AI_PERSONA=You are a billing specialist. Be clear about charges and payment options.)
 same => n,Set(CALLERID(name)=${ODBC_CUSTOMER_LOOKUP(${CALLERID(num)})})  ; Optional: CRM lookup
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

### 3.5 Advanced: After-Hours with Custom Greeting

```asterisk
[from-ai-agent-after-hours]
exten => s,1,NoOp(AI Agent - After Hours)
 same => n,Answer()
 same => n,Set(AI_CONTEXT=after_hours)
 same => n,Set(AI_GREETING=Thank you for calling. Our office is currently closed. I can help answer questions or take a message.)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

### 3.6 Create Custom Destinations

Create a FreePBX Custom Destination for each context you want to expose to IVRs or inbound routes.

**Steps:**

1. Navigate to: **Admin → Custom Destination**
2. Click **"Add"** to create a new destination
3. Set Target to your dialplan entry:
   - `from-ai-agent,s,1` (basic AI agent)
   - `from-ai-agent-support,s,1` (customer support context)
   - `from-ai-agent-sales,s,1` (sales context)
   - `from-ai-agent-billing,s,1` (billing context)
   - `from-ai-agent-after-hours,s,1` (after hours)
4. Give it a Description (e.g., "AI Agent - Customer Support")
5. Submit and **Apply Config**

Snapshot:

![Custom Destination - Target](freepbx/img/snapshot-2-custom-destination.png)

## 4. Deployment & Startup

### 4.1 Start Services

The `./install.sh` script starts the correct services automatically based on your configuration choice. To manually start or restart:

**For OpenAI Realtime or Deepgram** (cloud-only):
```bash
docker compose up -d --build ai-engine
```

**For Local Hybrid** (needs local models):
```bash
# Start local-ai-server first
docker compose up -d local-ai-server

# Wait for health (first start may take 5-10 min to load models)
docker compose logs -f local-ai-server

# Once healthy, start ai-engine
docker compose up -d --build ai-engine
```

### 4.2 Monitor Startup

```bash
# Watch ai-engine logs
docker compose logs -f ai-engine

# Look for these key messages:
# ✅ "Successfully connected to ARI"
# ✅ "AudioSocket server listening on 0.0.0.0:8090" (if using AudioSocket)
# ✅ "ExternalMedia RTP server started on 0.0.0.0:18080" (if using RTP)
# ✅ Provider initialization messages
```

### 4.3 Media Path Verification (For Pipeline Configurations)

Pipeline configurations (Local Hybrid) use file-based playback and need media path access:

```bash
# Verify the symlink exists
ls -ld /var/lib/asterisk/sounds/ai-generated

# Should show: /var/lib/asterisk/sounds/ai-generated -> /mnt/asterisk_media/ai-generated
```

**If missing**, the installer should have created it. If not:

```bash
sudo mkdir -p /mnt/asterisk_media/ai-generated /var/lib/asterisk/sounds
sudo ln -sfn /mnt/asterisk_media/ai-generated /var/lib/asterisk/sounds/ai-generated
sudo chown -R asterisk:asterisk /mnt/asterisk_media/ai-generated
```

**Note**: Cloud configurations (OpenAI Realtime, Deepgram) use streaming and don't require this.

## 5. Verification & Testing

### 5.1 Health Check

Verify the ai-engine is running and ready:

```bash
curl http://127.0.0.1:15000/health
```

**Expected response**:
```json
{
  "status": "healthy",
  "ari_connected": true,
  "audio_transport": "audiosocket",  // or "externalmedia"
  "active_configuration": "golden-openai"  // or golden-deepgram, golden-local-hybrid
}
```

### 5.2 Test Call

1. **Dial your Custom Destination** from a phone
2. **Expected behavior**:
   - Call is answered immediately
   - You hear the AI greeting within 1-2 seconds
   - You can speak and get intelligent responses
   - Conversation feels natural (no long delays)

3. **Monitor logs during the call**:

```bash
docker compose logs -f ai-engine | grep -E "Stasis|Audio|Provider|Greeting"
```

**Look for**:
- ✅ `StasisStart event received`
- ✅ `AudioSocket connection accepted` or `ExternalMedia channel created`
- ✅ Provider connection/greeting messages
- ✅ STT transcription logs
- ✅ LLM response logs  
- ✅ TTS playback logs

### 5.3 Monitor Performance Metrics (Optional)

```bash
# View Prometheus metrics
curl http://127.0.0.1:15000/metrics | grep ai_agent

# Key metrics to watch:
# - ai_agent_turn_latency_seconds: Time from user speech end to AI response start
# - ai_agent_stt_latency_seconds: Speech-to-text processing time
# - ai_agent_llm_latency_seconds: LLM response time
# - ai_agent_tts_latency_seconds: Text-to-speech generation time
```

## 6. Troubleshooting

### Common Issues

**❌ Call enters Stasis but no audio/greeting**

**Causes**:
- ARI connection failed
- Transport not started (AudioSocket/RTP server)
- Provider API key missing or invalid

**Solution**:
```bash
# Check ai-engine logs
docker compose logs ai-engine | tail -50

# Look for:
# ✅ "Successfully connected to ARI"
# ✅ "AudioSocket server listening" or "ExternalMedia RTP server started"
# ✅ Provider initialization (no API key errors)

# Verify .env has correct API keys
cat .env | grep API_KEY
```

---

**❌ Greeting plays but no response to speech**

**Causes**:
- VAD not detecting speech
- STT provider issue
- Microphone/audio quality issue

**Solution**:
```bash
# Check STT logs
docker compose logs ai-engine | grep -E "STT|transcription|utterance"

# Look for:
# ✅ "Utterance detected" or "Speech segment captured"
# ❌ If not appearing: VAD might be too aggressive or audio not reaching STT

# Try increasing VAD sensitivity in config/ai-agent.yaml:
# vad:
#   webrtc_aggressiveness: 0  # 0=least aggressive (best for telephony)
#   energy_threshold: 1200     # Lower = more sensitive
```

---

**❌ Long delays between responses**

**Causes**:
- Slow LLM responses
- Network latency
- Local models not loaded (Local Hybrid)

**Solution**:
```bash
# Check latency metrics
curl http://127.0.0.1:15000/metrics | grep latency

# For Local Hybrid: ensure local-ai-server is healthy
docker compose logs local-ai-server | tail -20

# Look for model loading messages
# Expected: "STT model loaded", "LLM model loaded", "TTS model loaded"
```

---

**❌ Audio cutting out or garbled**

**Causes**:
- Network jitter
- Buffer underruns
- Sample rate mismatch

**Solution**:
Check transport compatibility in `docs/Transport-Mode-Compatibility.md`

For pipelines (Local Hybrid): Must use ExternalMedia RTP + file playback
For full agents (OpenAI/Deepgram): Can use either transport + streaming

---

**❌ "Connection refused" errors**

**Causes**:
- Containers not running
- Ports not accessible
- Firewall blocking

**Solution**:
```bash
# Check container status
docker compose ps

# Verify ports are listening
netstat -tuln | grep -E "8090|18080|15000"

# Expected:
# tcp 0.0.0.0:8090  (AudioSocket)
# udp 0.0.0.0:18080 (ExternalMedia RTP)
# tcp 0.0.0.0:15000 (Health/metrics)
```

### Get Help

For additional troubleshooting:
- Check `docs/Configuration-Reference.md` for tuning parameters
- Review `docs/Transport-Mode-Compatibility.md` for transport issues
- See monitoring dashboards: `monitoring/README.md`
- Report issues: https://github.com/hkjarral/Asterisk-AI-Voice-Agent/issues

## 7. Next Steps

Once your integration is working:

1. **Customize for your use case**: Add context-specific routing per department
2. **Monitor performance**: Enable Prometheus + Grafana monitoring (see `monitoring/README.md`)
3. **Scale up**: Test with higher call volumes
4. **Explore features**: Try different AI providers, tune VAD/barge-in settings
5. **Production hardening**: Review `docs/PRODUCTION_DEPLOYMENT.md` (when available)

---

**FreePBX Integration Guide v4.0 - Complete** ✅

For questions or issues, see the [GitHub repository](https://github.com/hkjarral/Asterisk-AI-Voice-Agent).
