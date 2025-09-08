# TTS Service Testing Guide

This document describes how to test the TTS (Text-to-Speech) service components and functionality.

## Overview

The TTS service provides audio synthesis capabilities using OpenAI's TTS API with fallback to Asterisk SayAlpha. It includes comprehensive testing for:

- Audio synthesis and quality
- File management and shared volume access
- Redis message publishing
- Fallback mechanisms
- Performance under load
- Concurrent request handling

## Test Files

### Integration Tests (`test_tts_integration.py`)

Comprehensive integration tests covering the complete TTS pipeline:

- **OpenAI TTS Client**: Tests audio synthesis with different text lengths
- **Audio File Manager**: Tests file creation, retrieval, and cleanup
- **Asterisk Fallback**: Tests fallback mechanisms when OpenAI fails
- **TTS Service Integration**: Tests complete service workflow
- **Redis Publishing**: Tests message publishing to Redis channels
- **Concurrent Generation**: Tests multiple simultaneous requests
- **Shared Volume Access**: Tests file system permissions and access

### Performance Tests (`performance_test.py`)

Performance and load testing:

- **Single Synthesis Performance**: Measures synthesis time for different text lengths
- **File Management Performance**: Tests file creation and cleanup speed
- **Redis Publishing Performance**: Measures message publishing throughput
- **Concurrent Throughput**: Tests handling of multiple simultaneous requests
- **Memory Usage Under Load**: Monitors memory consumption during sustained load

### Test Runner (`run_tests.py`)

Simple script to run all tests with proper environment setup.

## Prerequisites

### Environment Variables

Ensure these environment variables are set:

```bash
export OPENAI_API_KEY="your-openai-api-key"
export REDIS_URL="redis://localhost:6379"
```

### Dependencies

Install required packages:

```bash
pip install openai redis.asyncio psutil tracemalloc
```

### Shared Volume

Ensure the shared volume is accessible:

```bash
mkdir -p /shared/audio
chmod 755 /shared/audio
```

## Running Tests

### Run All Tests

```bash
cd services/tts_service
python run_tests.py
```

### Run Individual Test Suites

```bash
# Integration tests only
python test_tts_integration.py

# Performance tests only
python performance_test.py
```

### Run with Docker

```bash
# Build and run tests in container
docker-compose exec tts_service python run_tests.py
```

## Test Configuration

### Integration Test Configuration

```python
TEST_CONFIG = {
    'redis_url': 'redis://localhost:6379',
    'openai_api_key': os.getenv('OPENAI_API_KEY'),
    'tts_voice': 'alloy',
    'tts_base_directory': '/shared/audio',
    'tts_file_ttl': 3600,
    'tts_enable_fallback': True,
    'tts_fallback_mode': 'sayalpha',
    'asterisk_host': 'localhost',
    'asterisk_port': 8088,
    'ari_username': 'AIAgent',
    'ari_password': 'c4d5359e2f9ddd394cd6aa116c1c6a96'
}
```

### Performance Test Configuration

```python
PERF_CONFIG = {
    'concurrent_requests': 10,
    'test_duration_seconds': 60,
    'text_samples': [
        "Short test message",
        "Medium length test message with more content",
        "Very long test message with extensive content for comprehensive testing"
    ]
}
```

## Expected Results

### Integration Tests

All tests should pass with:

- ✅ OpenAI TTS client test passed
- ✅ Audio file manager test passed
- ✅ Asterisk fallback test passed (may fail in test env without Asterisk)
- ✅ TTS service integration test passed
- ✅ Redis message publishing test passed
- ✅ Concurrent audio generation test passed
- ✅ Shared volume access test passed

### Performance Tests

Typical performance metrics:

- **Synthesis Time**: 1-3 seconds for typical text
- **File Creation**: <100ms per file
- **Redis Publishing**: >1000 messages/second
- **Concurrent Throughput**: 5-10 requests/second
- **Memory Usage**: <200MB under normal load

## Troubleshooting

### Common Issues

1. **OpenAI API Key Missing**
   ```
   ❌ OPENAI_API_KEY environment variable not set
   ```
   Solution: Set the environment variable with your OpenAI API key.

2. **Redis Connection Failed**
   ```
   ❌ Redis connection failed: [Errno 111] Connection refused
   ```
   Solution: Ensure Redis is running on localhost:6379.

3. **Shared Volume Access Denied**
   ```
   ❌ Shared volume access test failed: Permission denied
   ```
   Solution: Check directory permissions: `chmod 755 /shared/audio`

4. **Asterisk Fallback Fails**
   ```
   ❌ Asterisk fallback test failed: Connection refused
   ```
   Expected in test environment without Asterisk. This is normal.

### Debug Mode

Run tests with debug logging:

```bash
PYTHONPATH=. python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
import asyncio
from test_tts_integration import TTSIntegrationTester
asyncio.run(TTSIntegrationTester().run_all_tests())
"
```

## Test Data

### Sample Texts

Tests use various text samples:

- **Short**: "Hello, this is a test message."
- **Medium**: "This is a medium length test message with more content."
- **Long**: "This is a very long test message that contains many words and should provide a good test of the TTS service performance under load with realistic text content."

### Audio Formats

Tests validate:

- **Format**: WAV (16-bit, 16kHz)
- **Codec**: PCM
- **Channels**: Mono
- **Sample Rate**: 16kHz

## Continuous Integration

### GitHub Actions

Add to `.github/workflows/test.yml`:

```yaml
- name: Test TTS Service
  run: |
    cd services/tts_service
    python run_tests.py
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    REDIS_URL: redis://localhost:6379
```

### Docker Testing

```bash
# Test in container environment
docker-compose up -d redis
docker-compose exec tts_service python run_tests.py
```

## Performance Benchmarks

### Baseline Metrics

| Metric | Target | Typical |
|--------|--------|---------|
| Synthesis Time | <3s | 1-2s |
| File Creation | <100ms | 50ms |
| Redis Publishing | >1000 msg/s | 2000+ msg/s |
| Concurrent Throughput | >5 req/s | 8-10 req/s |
| Memory Usage | <200MB | 150MB |

### Load Testing

For production load testing:

```bash
# Increase concurrent requests
PERF_CONFIG['concurrent_requests'] = 50

# Longer test duration
PERF_CONFIG['test_duration_seconds'] = 300

# Run performance tests
python performance_test.py
```

## Monitoring

### Health Checks

Monitor TTS service health:

```bash
# Check service status
curl http://localhost:18003/health

# Check Redis connectivity
redis-cli ping

# Check shared volume
ls -la /shared/audio/
```

### Logs

Monitor service logs:

```bash
# Docker logs
docker-compose logs tts_service

# System logs
tail -f /var/log/asterisk-ai-voice-agent/tts_service.log
```

## Contributing

When adding new tests:

1. Follow the existing test structure
2. Add appropriate error handling
3. Include performance metrics where relevant
4. Update this documentation
5. Ensure tests are deterministic and repeatable

## Support

For issues with testing:

1. Check the troubleshooting section
2. Review logs for specific error messages
3. Verify environment configuration
4. Test individual components separately
5. Contact the development team for assistance
