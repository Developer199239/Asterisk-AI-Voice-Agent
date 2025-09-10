#!/usr/bin/env python3
"""
TTS Service Test Runner

Simple script to run all TTS service tests.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the service directory to Python path
service_dir = Path(__file__).parent
sys.path.insert(0, str(service_dir))

async def run_integration_tests():
    """Run integration tests."""
    print("Running TTS Service Integration Tests...")
    print("=" * 50)
    
    try:
        from test_tts_integration import TTSIntegrationTester
        tester = TTSIntegrationTester()
        success = await tester.run_all_tests()
        return success
    except Exception as e:
        print(f"Integration tests failed: {e}")
        return False

async def run_performance_tests():
    """Run performance tests."""
    print("\nRunning TTS Service Performance Tests...")
    print("=" * 50)
    
    try:
        from performance_test import TTSPerformanceTester
        tester = TTSPerformanceTester()
        success = await tester.run_performance_tests()
        return success
    except Exception as e:
        print(f"Performance tests failed: {e}")
        return False

async def main():
    """Main test runner."""
    print("TTS Service Test Suite")
    print("=" * 50)
    
    # Check if OpenAI API key is available
    if not os.getenv('OPENAI_API_KEY'):
        print("❌ OPENAI_API_KEY environment variable not set")
        print("Please set your OpenAI API key before running tests")
        return 1
    
    # Run tests
    integration_success = await run_integration_tests()
    performance_success = await run_performance_tests()
    
    # Summary
    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)
    print(f"Integration Tests: {'✅ PASS' if integration_success else '❌ FAIL'}")
    print(f"Performance Tests: {'✅ PASS' if performance_success else '❌ FAIL'}")
    
    overall_success = integration_success and performance_success
    print(f"Overall Result: {'✅ ALL TESTS PASSED' if overall_success else '❌ SOME TESTS FAILED'}")
    
    return 0 if overall_success else 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
