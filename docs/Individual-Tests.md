# Individual Component Tests

This document describes the comprehensive test suite for the Asterisk AI Voice Agent v3.0, designed to systematically verify each component of the two-container architecture.

## Test Files Overview

### 1. `test_local_ai_server.py` - Local AI Server Container Tests
**Purpose**: Tests the heavy AI processing container that handles STT, LLM, and TTS operations.

**Location**: `local_ai_server/test_local_ai_server.py`

**Tests Performed**:
- ✅ **WebSocket Server Test**: Verifies server is running and accepting connections on port 8765
- ✅ **Model Files Test**: Checks if all AI model files exist in correct locations
- ✅ **STT Functionality Test**: Tests Speech-to-Text processing with Vosk
- ✅ **LLM Functionality Test**: Tests Large Language Model processing with TinyLlama
- ❌ **TTS Functionality Test**: Tests Text-to-Speech processing (currently failing)
- ❌ **Greeting Message Test**: Tests greeting message handling via WebSocket
- ❌ **Audio Message Test**: Tests complete audio processing pipeline

**Run Command**:
```bash
docker exec local_ai_server python /app/test_local_ai_server.py
```

### 2. `test_ai_engine.py` - AI Engine Container Tests
**Purpose**: Tests the lean controller container that communicates with Asterisk via ARI.

**Location**: `test_ai_engine.py`

**Tests Performed**:
- ✅ **ARI Connection Test**: Verifies connection to Asterisk REST Interface
- ✅ **Audio Playback Test**: Tests audio file creation in shared media directory
- ❌ **WebSocket Connection Test**: Tests connection to Local AI Server
- ❌ **Snoop Channel Test**: Tests snoop channel creation (requires active call)

**Run Command**:
```bash
docker exec ai_engine python /app/test_ai_engine.py
```

### 3. `test_integration.py` - End-to-End Integration Tests
**Purpose**: Tests the complete flow between both containers.

**Location**: `test_integration.py`

**Tests Performed**:
- **Complete Greeting Flow**: Tests greeting message → TTS → audio response
- **Audio Processing Flow**: Tests STT → LLM → TTS pipeline
- **ARI Playback Simulation**: Tests audio file creation and format validation
- **WebSocket Stability**: Tests multiple simultaneous connections

**Run Command**:
```bash
docker exec ai_engine python /app/test_integration.py
```

## Test Results Summary

### Current Status (Latest Run)

#### Local AI Server Tests: 4/7 PASSED
- ✅ WebSocket Server: PASS
- ✅ Model Files: PASS  
- ✅ STT Functionality: PASS
- ✅ LLM Functionality: PASS
- ❌ TTS Functionality: FAIL - `could not create a primitive` error
- ❌ Greeting Message: FAIL - WebSocket connection closed unexpectedly
- ❌ Audio Message: FAIL - No response within 20 seconds

#### AI Engine Tests: 2/4 PASSED
- ✅ ARI Connection: PASS
- ✅ Audio Playback: PASS
- ❌ WebSocket Connection: FAIL - Cannot connect to Local AI Server
- ❌ Snoop Channel: FAIL - No active channels (expected, no call in progress)

## Key Issues Identified

### 1. TTS System Failure
**Error**: `could not create a primitive`
**Impact**: Prevents greeting audio generation and complete audio processing
**Status**: Critical - Blocking all audio output

### 2. WebSocket Connection Issues
**Error**: AI Engine cannot connect to Local AI Server
**Impact**: Prevents communication between containers
**Status**: Critical - Blocking container communication

### 3. Greeting Message Handling
**Error**: WebSocket connection closed unexpectedly during greeting processing
**Impact**: No initial greeting audio played to callers
**Status**: High - Affects user experience

## Test Execution Workflow

### Recommended Testing Sequence

1. **Start with Local AI Server Tests**
   ```bash
   docker exec local_ai_server python /app/test_local_ai_server.py
   ```
   - Verifies AI models are loaded and functional
   - Identifies TTS issues early

2. **Run AI Engine Tests**
   ```bash
   docker exec ai_engine python /app/test_ai_engine.py
   ```
   - Verifies ARI connectivity
   - Tests audio file creation

3. **Run Integration Tests**
   ```bash
   docker exec ai_engine python /app/test_integration.py
   ```
   - Tests complete end-to-end flow
   - Verifies container communication

4. **Make Test Call**
   - Monitor logs during actual call
   - Verify real-world functionality

## Troubleshooting Guide

### TTS Issues
- Check TTS model initialization
- Verify audio format compatibility
- Test TTS API method calls

### WebSocket Issues
- Verify Local AI Server is running
- Check port 8765 availability
- Test connection from AI Engine container

### Greeting Issues
- Verify greeting message handling in Local AI Server
- Check TTS audio generation
- Test audio response format

## Test File Maintenance

### Adding New Tests
1. Add test methods to appropriate test file
2. Update test results documentation
3. Add run commands to this document

### Updating Tests
1. Modify test logic as needed
2. Update expected results
3. Document changes in this file

### Test File Deployment
```bash
# Deploy to server
scp test_*.py root@voiprnd.nemtclouddispatch.com:/root/Asterisk-Agent-Develop/
scp local_ai_server/test_*.py root@voiprnd.nemtclouddispatch.com:/root/Asterisk-Agent-Develop/local_ai_server/

# Make executable
ssh root@voiprnd.nemtclouddispatch.com "chmod +x /root/Asterisk-Agent-Develop/test_*.py"
```

## Expected Test Results

### Successful System
- All Local AI Server tests: 7/7 PASSED
- All AI Engine tests: 4/4 PASSED  
- All Integration tests: 4/4 PASSED
- Test call with audible greeting and conversation

### Current Blockers
- TTS system failure preventing audio generation
- WebSocket connection issues preventing container communication
- Greeting message handling failure

## Next Steps

1. Fix TTS system failure
2. Resolve WebSocket connection issues
3. Verify greeting message handling
4. Test complete end-to-end flow
5. Validate real-time conversation capabilities
