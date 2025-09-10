#!/usr/bin/env python3
"""
STT Service Test Runner

This script runs comprehensive tests for the STT service components.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent / "shared"))

from test_stt_integration import run_integration_tests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Main test runner."""
    logger.info("Starting STT Service Test Suite")
    
    try:
        # Run integration tests
        success = await run_integration_tests()
        
        if success:
            logger.info("✅ All tests passed!")
            return 0
        else:
            logger.error("❌ Some tests failed!")
            return 1
            
    except Exception as e:
        logger.error(f"Test runner error: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
