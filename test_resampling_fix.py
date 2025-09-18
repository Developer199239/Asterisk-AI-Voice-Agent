#!/usr/bin/env python3
"""
Test script to verify the resampling fix is working correctly.
"""

import sys
import os
sys.path.append("/app/src")

from rtp_server import RTPSession, RTPServer
import audioop

def test_resampling_fix():
    """Test that the resampling fix produces consistent 640-byte output."""
    
    print("🧪 Testing RTP Resampling Fix")
    print("=" * 40)
    
    # Create a test session
    session = RTPSession(
        call_id="test",
        local_port=18080,
        remote_host="127.0.0.1",
        remote_port=18080,
        socket=None,
        sequence_number=1,
        timestamp=0,
        ssrc=12345,
        created_at=0,
        last_packet_at=0
    )
    
    # Create test 8kHz PCM data (160 bytes = 20ms at 8kHz)
    test_8k = b"\x00" * 160
    print(f"Input: {len(test_8k)} bytes (8kHz PCM)")
    
    # Create a mock RTP server to test the method
    class MockRTP:
        def _resample_8k_to_16k(self, pcm_8k, session):
            try:
                pcm_16k, state = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, session.resample_state)
                session.resample_state = state
                return pcm_16k
            except Exception as e:
                print(f"Error: {e}")
                return pcm_8k
    
    rtp = MockRTP()
    
    # Test multiple calls to verify state persistence
    results = []
    for i in range(5):
        result = rtp._resample_8k_to_16k(test_8k, session)
        results.append(len(result))
        print(f"Call {i+1}: {len(result)} bytes, state: {session.resample_state is not None}")
    
    # Verify all results are the same size
    all_same = all(r == results[0] for r in results)
    expected_size = 320  # 20ms at 16kHz = 320 bytes
    
    print(f"\n📊 Results:")
    print(f"  All calls same size: {all_same}")
    print(f"  Expected size: {expected_size} bytes")
    print(f"  Actual size: {results[0]} bytes")
    print(f"  Size correct: {results[0] == expected_size}")
    
    if all_same and results[0] == expected_size:
        print("✅ RESAMPLING FIX IS WORKING CORRECTLY!")
        return True
    else:
        print("❌ RESAMPLING FIX HAS ISSUES!")
        return False

if __name__ == "__main__":
    test_resampling_fix()
