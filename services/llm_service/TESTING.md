# LLM Service Testing Guide

This document provides comprehensive testing information for the LLM service, including unit tests, integration tests, and performance tests.

## Overview

The LLM service testing suite includes:
- **Unit Tests**: Individual component testing
- **Integration Tests**: End-to-end service testing
- **Performance Tests**: Load and performance testing
- **Concurrency Tests**: Multi-channel isolation testing

## Test Structure

```
services/llm_service/
├── test_llm_integration.py    # Integration tests
├── run_tests.py              # Test runner script
├── performance_test.py        # Performance testing
└── TESTING.md                # This documentation
```

## Running Tests

### Quick Test Run
```bash
cd services/llm_service
python run_tests.py
```

### Individual Test Suites

#### Integration Tests
```bash
python test_llm_integration.py
```

#### Performance Tests
```bash
python performance_test.py
```

### Using pytest (if available)
```bash
pytest test_llm_integration.py -v
```

## Test Categories

### 1. Unit Tests

**Purpose**: Test individual components in isolation

**Components Tested**:
- `ConversationManager` class
- `OpenAIClient` class
- `LLMService` class
- Token counting functionality
- Redis operations

**Key Test Cases**:
- Conversation creation and retrieval
- Message addition and history management
- Token counting accuracy
- Error handling and recovery

### 2. Integration Tests

**Purpose**: Test complete service workflows

**Test Scenarios**:
- **Conversation Creation and Isolation**: Verify channel-based context isolation
- **Concurrent Conversation Handling**: Test multiple simultaneous conversations
- **Token Limit Management**: Test conversation truncation when limits are exceeded
- **Fallback Model Activation**: Test graceful degradation when primary model fails
- **Conversation Persistence**: Test data persistence across service restarts
- **Error Handling and Recovery**: Test resilience to various failure scenarios
- **Performance Under Load**: Test service behavior under high load

**Key Assertions**:
- Conversations are properly isolated by channel ID
- Messages are correctly added to conversation history
- Token limits are respected and enforced
- Fallback models activate when primary fails
- Data persists across service restarts
- Errors are handled gracefully without service crashes

### 3. Performance Tests

**Purpose**: Measure and validate service performance

**Performance Metrics**:
- **Conversation Creation Rate**: Conversations created per second
- **Message Processing Rate**: Messages processed per second
- **Token Counting Rate**: Token counting operations per second
- **Concurrent Operations**: Performance under concurrent load
- **Memory Usage**: Memory consumption patterns
- **Response Times**: API response latencies

**Test Scenarios**:
- Sequential vs concurrent conversation creation
- Message processing under various loads
- Token counting performance with different text lengths
- Conversation truncation performance
- Concurrent channel isolation performance

**Performance Thresholds**:
- Conversation creation: >10 conversations/second
- Message processing: >50 messages/second
- Token counting: >1000 texts/second
- Channel isolation: 100% accuracy under load

## Test Configuration

### Environment Variables

```bash
# Redis configuration
REDIS_URL=redis://localhost:6379

# OpenAI configuration
OPENAI_API_KEY=your-api-key-here
OPENAI_BASE_URL=https://api.openai.com/v1

# LLM configuration
LLM_PRIMARY_MODEL=gpt-4o
LLM_FALLBACK_MODEL=gpt-3.5-turbo
LLM_TEMPERATURE=0.8
LLM_MAX_TOKENS=4096
LLM_CONVERSATION_TTL=3600
LLM_MAX_CONVERSATION_TOKENS=4000
LLM_SYSTEM_MESSAGE="You are a helpful AI assistant for Jugaar LLC."
LLM_DEBUG_LOGGING=true
```

### Mock Services

Tests use mocked services to avoid external dependencies:
- **Redis**: Mocked with `AsyncMock` for all operations
- **OpenAI API**: Mocked responses for consistent testing
- **Network calls**: All external calls are mocked

## Test Data

### Sample Conversations

Tests use various conversation patterns:
- Short messages: "Hello"
- Medium messages: "This is a medium length message"
- Long messages: Repeated text to test token limits
- Mixed content: Various message types in sequence

### Channel Patterns

- Sequential: `channel_001`, `channel_002`, etc.
- Performance: `perf_channel_0001`, `perf_channel_0002`, etc.
- Isolation: `isolation_channel_000`, `isolation_channel_001`, etc.

## Troubleshooting

### Common Issues

1. **Import Errors**
   - Ensure shared modules are in the Python path
   - Check that all dependencies are installed

2. **Redis Connection Errors**
   - Tests use mocked Redis, but ensure Redis is available for integration testing
   - Check Redis URL configuration

3. **OpenAI API Errors**
   - Tests use mocked OpenAI responses
   - For real API testing, ensure valid API key is configured

4. **Performance Test Failures**
   - Check system resources (CPU, memory)
   - Adjust performance thresholds if needed
   - Run tests on dedicated test environment

### Debug Mode

Enable debug logging for detailed test output:
```bash
export LLM_DEBUG_LOGGING=true
python run_tests.py
```

### Verbose Output

For detailed test progress:
```bash
python run_tests.py --verbose
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: LLM Service Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.11
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests
        run: cd services/llm_service && python run_tests.py
```

## Test Coverage

### Current Coverage Areas
- ✅ Conversation management
- ✅ Channel isolation
- ✅ Token counting and limits
- ✅ Error handling
- ✅ Performance metrics
- ✅ Concurrent operations

### Areas for Improvement
- 🔄 Real Redis integration testing
- 🔄 Real OpenAI API testing
- 🔄 Memory leak detection
- 🔄 Long-running stability tests

## Contributing

### Adding New Tests

1. **Unit Tests**: Add to existing test methods
2. **Integration Tests**: Add new test methods to `TestLLMServiceIntegration`
3. **Performance Tests**: Add new test methods to `LLMServicePerformanceTester`

### Test Naming Convention

- Unit tests: `test_<component>_<functionality>`
- Integration tests: `test_<scenario>_<expected_behavior>`
- Performance tests: `test_<operation>_performance`

### Test Documentation

- Document test purpose and expected behavior
- Include performance thresholds and metrics
- Add troubleshooting information for complex tests

## Monitoring and Alerting

### Key Metrics to Monitor

1. **Service Health**
   - Conversation creation success rate
   - Message processing success rate
   - Error rate and types

2. **Performance**
   - Response times
   - Throughput rates
   - Resource utilization

3. **Data Integrity**
   - Channel isolation accuracy
   - Conversation persistence reliability
   - Token counting accuracy

### Alert Thresholds

- Error rate > 5%
- Response time > 2 seconds
- Memory usage > 80%
- Failed channel isolation > 0%

## Best Practices

1. **Test Isolation**: Each test should be independent
2. **Mock External Dependencies**: Avoid external service calls in tests
3. **Performance Baselines**: Establish and maintain performance baselines
4. **Error Scenarios**: Test both success and failure paths
5. **Concurrent Testing**: Always test concurrent scenarios
6. **Resource Cleanup**: Ensure proper cleanup after tests
7. **Documentation**: Keep test documentation up to date
