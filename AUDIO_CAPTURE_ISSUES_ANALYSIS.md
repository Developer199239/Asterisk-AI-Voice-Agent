# Audio Capture & Recording Issues Analysis

## 🔍 Issue #1: Tap Audios Not Being Created

### **Root Causes Identified:**

#### **1. Wrong Directory**
```python
# src/engine.py line 228
self.audio_capture = AudioCaptureManager()  # ❌ No base_dir passed!

# Defaults to hardcoded path (src/utils/audio_capture.py line 12)
def __init__(self, base_dir: str = "/tmp/ai-engine-captures"):

# But environment variable sets:
DIAG_TAP_OUTPUT_DIR=/tmp/ai-engine-taps  # ❌ Never used!
```

**Result:** Files created in `/tmp/ai-engine-captures` instead of `/tmp/ai-engine-taps`

---

#### **2. Files Deleted on Call End**
```python
# src/utils/audio_capture.py lines 113-129
def close_call(self, call_id: str) -> None:
    # ... closes wave files ...
    # Then DELETES ALL CAPTURED FILES! ❌
    for name in os.listdir(call_dir):
        fpath = os.path.join(call_dir, name)
        if os.path.isfile(fpath):
            os.remove(fpath)  # ❌ DELETES TAP FILES!
    os.rmdir(call_dir)
```

**Result:** Even if files were in correct location, they'd be deleted immediately after call ends!

---

### **The Fix:**

#### **Step 1: Pass correct directory to AudioCaptureManager**

```python
# src/engine.py line 228
# OLD:
self.audio_capture = AudioCaptureManager()

# NEW:
tap_dir = streaming_config.get('diag_out_dir', '/tmp/ai-engine-taps')
self.audio_capture = AudioCaptureManager(base_dir=tap_dir)
```

#### **Step 2: Only delete files if NOT diagnostic mode**

```python
# src/utils/audio_capture.py - Add parameter to __init__
def __init__(self, base_dir: str = "/tmp/ai-engine-captures", keep_files: bool = False):
    self.base_dir = base_dir
    self.keep_files = keep_files  # NEW
    # ... rest of init ...

# Modify close_call to respect keep_files
def close_call(self, call_id: str) -> None:
    keys_to_close = []
    with self._lock:
        for key, (wf, _rate) in list(self._handles.items()):
            if key[0] == call_id:
                try:
                    wf.close()
                except Exception:
                    pass
                keys_to_close.append(key)
        for key in keys_to_close:
            self._handles.pop(key, None)
    
    # Only delete files if not in diagnostic mode
    if not self.keep_files:  # NEW
        try:
            call_dir = os.path.join(self.base_dir, call_id)
            # ... deletion code ...
        except Exception:
            pass
```

#### **Step 3: Pass keep_files flag from config**

```python
# src/engine.py line 228
tap_dir = streaming_config.get('diag_out_dir', '/tmp/ai-engine-taps')
keep_taps = streaming_config.get('diag_enable_taps', False)
self.audio_capture = AudioCaptureManager(base_dir=tap_dir, keep_files=keep_taps)
```

---

## 🔍 Issue #2: Call Recordings Not Found

### **Root Causes:**

#### **1. No MixMonitor Started**
- Engine doesn't call `MixMonitor` ARI command
- Recordings only exist from October (old test calls)
- No recordings for recent calls (176318xxxx)

#### **2. No Dialplan Recording**
- Dialplan doesn't have `MixMonitor` or `Record` application
- Recording must be started explicitly

---

### **The Fix:**

#### **Option A: Add Recording in Engine (ARI-based)**

```python
# src/engine.py - In _on_stasis_start after bridge creation
async def _on_stasis_start(self, channel, event):
    # ... existing code ...
    
    # Start call recording
    if self.config.get('enable_recording', False):
        recording_name = f"out-{channel_id}"
        recording_dir = "/var/spool/asterisk/recording"
        recording_file = f"{recording_dir}/{recording_name}"
        
        try:
            await self.ari_client.channels.record(
                channelId=channel_id,
                name=recording_name,
                format="wav",
                maxDurationSeconds=3600,  # 1 hour max
                ifExists="overwrite",
            )
            logger.info(
                "📹 Recording started",
                call_id=channel_id,
                file=recording_file,
            )
        except Exception as e:
            logger.warning(
                "⚠️ Recording failed to start",
                call_id=channel_id,
                error=str(e),
            )
```

#### **Option B: Add Recording in Dialplan (Asterisk-based)**

```asterisk
; extensions_custom.conf
[from-ai-agent]
exten => s,1,NoOp(AI Voice Agent v4.0)
same => n,Set(AI_CONTEXT=demo_google_live)
same => n,Set(AI_PROVIDER=google_live)
; NEW: Start recording before Stasis
same => n,MixMonitor(/var/spool/asterisk/monitor/${UNIQUEID}.wav,b)
same => n,Stasis(asterisk-ai-voice-agent)
same => n,Hangup()
```

---

## 📊 Current State Summary

### **Tap Audios:**
- ✅ Environment: `DIAG_ENABLE_TAPS=true` set
- ✅ Directory exists: `/tmp/ai-engine-taps/` (empty)
- ❌ Files never created: Wrong directory used
- ❌ Would be deleted anyway: `close_call()` deletes all files

### **Call Recordings:**
- ✅ Directory exists: `/var/spool/asterisk/monitor/`
- ❌ Old recordings only: From October (176066xxxx calls)
- ❌ No recent recordings: No `MixMonitor` or `Record` started
- ❌ Engine doesn't start recording: No ARI recording calls

---

## 🔧 Implementation Priority

### **High Priority - Fix Tap Audios:**
1. Pass `streaming_config['diag_out_dir']` to AudioCaptureManager ✅
2. Add `keep_files` parameter to prevent deletion ✅
3. Test: Make call, verify files in `/tmp/ai-engine-taps/` ✅

### **Medium Priority - Add Call Recording:**
1. Choose Option A (ARI) or Option B (Dialplan)
2. Implement recording start
3. Test: Make call, verify file in `/var/spool/asterisk/`

---

## 🧪 Testing Commands

### **Verify Tap Creation:**
```bash
# Before call
ssh root@voiprnd.nemtclouddispatch.com 'docker exec ai_engine ls -lah /tmp/ai-engine-taps/'

# After call (should see files)
ssh root@voiprnd.nemtclouddispatch.com 'docker exec ai_engine ls -lah /tmp/ai-engine-taps/'

# Copy taps locally
scp -r root@voiprnd.nemtclouddispatch.com:/var/lib/docker/volumes/asterisk-ai-voice-agent_ai-engine-data/_data/tmp/ai-engine-taps/ ./taps/
```

### **Verify Recordings:**
```bash
ssh root@voiprnd.nemtclouddispatch.com 'ls -lah /var/spool/asterisk/monitor/ | tail -10'
```

---

## 📝 Why This Matters for Google Live Debugging

With working tap audios, we can:
1. **Listen to actual raw audio** sent to Google Live
2. **Verify if resampling produces audible quality**
3. **Hear if it's noise vs actual speech**
4. **Compare input vs output audio**
5. **Confirm if issue is audio source or provider**

This will **definitively answer** whether the problem is:
- ✅ Microphone/phone quality
- ✅ SIP trunk audio
- ✅ Engine resampling artifacts
- ✅ Google Live sensitivity

Without taps, we're debugging blind!
