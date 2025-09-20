#!/usr/bin/env python3
"""
Test captured audio using the EXACT same approach as the AI engine.
This replicates the AI engine's send_audio method call to the LocalProvider.
"""

import asyncio
import websockets
import base64
import json
import logging
import os
import glob
import struct
import time
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

LOCAL_AI_SERVER_URL = "ws://localhost:8765/ws"

def combine_audio_frames(file_groups: dict, frames_per_segment: int = 50):
    """Combine multiple 20ms frames into longer audio segments for STT testing"""
    logging.info(f"Combining audio frames into segments of {frames_per_segment} frames each")
    
    combined_segments = []
    
    for file_type, files in file_groups.items():
        logging.info(f"Processing {file_type} files...")
        
        # Sort files by timestamp (filename contains timestamp)
        sorted_files = sorted(files)
        
        # Group files into segments
        for i in range(0, len(sorted_files), frames_per_segment):
            segment_files = sorted_files[i:i+frames_per_segment]
            if len(segment_files) < 10:  # Skip segments with too few files
                continue
                
            # Combine audio data
            combined_audio = b""
            for filepath in segment_files:
                try:
                    with open(filepath, "rb") as f:
                        audio_data = f.read()
                        combined_audio += audio_data
                except Exception as e:
                    logging.warning(f"Error reading {filepath}: {e}")
                    continue
            
            if len(combined_audio) > 0:
                segment_info = {
                    "type": file_type,
                    "segment_id": len(combined_segments),
                    "file_count": len(segment_files),
                    "total_bytes": len(combined_audio),
                    "duration_ms": len(combined_audio) // 32,  # 16kHz = 32 bytes per ms
                    "files": [os.path.basename(f) for f in segment_files]
                }
                combined_segments.append((combined_audio, segment_info))
    
    logging.info(f"Created {len(combined_segments)} combined audio segments")
    return combined_segments

async def test_ai_engine_approach(combined_audio: bytes, segment_info: dict):
    """Test using the EXACT same approach as AI engine's LocalProvider.send_audio()"""
    logging.info(f"Testing segment {segment_info['segment_id']}: {segment_info['file_count']} files, {segment_info['total_bytes']} bytes, {segment_info['duration_ms']}ms")
    
    try:
        # EXACT REPLICATION of LocalProvider.send_audio() method
        # This is the same JSON structure and WebSocket call the AI engine uses
        
        msg = json.dumps({
            "type": "audio", 
            "data": base64.b64encode(combined_audio).decode('utf-8'),
            "rate": 16000,
            "format": "pcm16le"
        })
        
        # Connect to local AI server (same as AI engine does)
        async with websockets.connect(LOCAL_AI_SERVER_URL) as websocket:
            # Send exactly as AI engine does
            await websocket.send(msg)
            logging.info(f"✅ Sent audio to STT: {len(combined_audio)} bytes")
            
            # Wait for response (TTS audio)
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=15)
                logging.info(f"✅ Received TTS response: {len(response)} bytes")
                
                return {
                    "status": "success",
                    "audio_bytes_sent": len(combined_audio),
                    "tts_bytes_received": len(response),
                    "segment_info": segment_info
                }
                
            except asyncio.TimeoutError:
                logging.warning(f"⏰ Timeout waiting for TTS response")
                return {
                    "status": "timeout",
                    "segment_info": segment_info
                }
            except Exception as e:
                logging.error(f"❌ Error receiving response: {e}")
                return {
                    "status": "response_error",
                    "error": str(e),
                    "segment_info": segment_info
                }
                
    except Exception as e:
        logging.error(f"❌ Connection error: {e}")
        return {
            "status": "connection_error",
            "error": str(e),
            "segment_info": segment_info
        }

def analyze_audio_files(capture_dir: str):
    """Analyze the captured audio files to understand the data"""
    logging.info(f"Analyzing audio files in: {capture_dir}")
    
    raw_files = glob.glob(os.path.join(capture_dir, "*.raw"))
    logging.info(f"Found {len(raw_files)} .raw files")
    
    # Group files by type
    file_groups = defaultdict(list)
    file_sizes = defaultdict(int)
    
    for filepath in sorted(raw_files):
        filename = os.path.basename(filepath)
        
        # Parse filename: 0001_rtp_ssrc_230021204_raw_rtp_all_220756_417.raw
        parts = filename.split('_')
        if len(parts) >= 4:
            file_type = f"{parts[2]}_{parts[3]}"  # e.g., "ssrc_raw" or "1758319668.236_raw"
        else:
            file_type = "unknown"
        
        file_groups[file_type].append(filepath)
        
        # Get file size
        try:
            size = os.path.getsize(filepath)
            file_sizes[file_type] += size
        except:
            pass
    
    # Print analysis
    logging.info("\n📊 AUDIO FILE ANALYSIS")
    logging.info("=" * 50)
    for file_type, files in file_groups.items():
        logging.info(f"{file_type}: {len(files)} files, {file_sizes[file_type]} bytes total")
        if files:
            avg_size = file_sizes[file_type] // len(files)
            logging.info(f"  Average size: {avg_size} bytes per file")
    
    return file_groups

async def test_audio_segments(combined_segments: list, max_segments: int = 10):
    """Test combined audio segments using AI engine approach"""
    logging.info(f"\n🧪 TESTING WITH AI ENGINE APPROACH (max {max_segments})")
    logging.info("=" * 50)
    
    results = []
    
    # Test up to max_segments
    test_segments = combined_segments[:max_segments]
    
    for i, (combined_audio, segment_info) in enumerate(test_segments):
        logging.info(f"\n--- Testing segment {i+1}/{len(test_segments)} ---")
        
        result = await test_ai_engine_approach(combined_audio, segment_info)
        results.append(result)
        
        # Small delay between tests
        await asyncio.sleep(1.0)
    
    return results

def print_results(results: list):
    """Print test results summary"""
    logging.info("\n📋 AI ENGINE APPROACH TEST RESULTS")
    logging.info("=" * 50)
    
    total_tests = len(results)
    success = sum(1 for r in results if r["status"] == "success")
    timeouts = sum(1 for r in results if r["status"] == "timeout")
    errors = sum(1 for r in results if r["status"] in ["response_error", "connection_error"])
    
    logging.info(f"Total segments tested: {total_tests}")
    logging.info(f"Success: {success} ({success/total_tests*100:.1f}%)")
    logging.info(f"Timeouts: {timeouts} ({timeouts/total_tests*100:.1f}%)")
    logging.info(f"Errors: {errors} ({errors/total_tests*100:.1f}%)")
    
    # Show details for successful segments
    if success > 0:
        logging.info("\n✅ Successfully processed segments:")
        for result in results:
            if result["status"] == "success":
                seg = result["segment_info"]
                logging.info(f"  Segment {seg['segment_id']}: {seg['file_count']} files, {seg['duration_ms']}ms")
                logging.info(f"    Audio sent: {result['audio_bytes_sent']} bytes")
                logging.info(f"    TTS received: {result['tts_bytes_received']} bytes")

async def main():
    logging.info("🎤 AI ENGINE APPROACH STT TEST")
    logging.info("=" * 50)
    logging.info("Using EXACT same approach as AI engine's LocalProvider.send_audio()")
    
    # Find the latest capture directory
    capture_dirs = sorted(glob.glob("/app/audio_capture_*/"), reverse=True)
    if not capture_dirs:
        logging.error("No audio capture directories found!")
        return
    
    latest_capture_dir = capture_dirs[0]
    logging.info(f"Using latest capture directory: {latest_capture_dir}")
    
    # Analyze the captured files
    file_groups = analyze_audio_files(latest_capture_dir)
    
    if not file_groups:
        logging.error("No audio files found in capture directory!")
        return
    
    # Combine audio frames into longer segments (like VAD utterances)
    combined_segments = combine_audio_frames(file_groups, frames_per_segment=100)  # 100 frames = 2 seconds
    
    if not combined_segments:
        logging.error("No combined audio segments created!")
        return
    
    # Test using AI engine approach
    results = await test_audio_segments(combined_segments, max_segments=5)
    
    # Print results
    print_results(results)
    
    logging.info("\n✅ Testing complete!")
    logging.info("This used the EXACT same approach as the AI engine's LocalProvider.send_audio() method.")
    logging.info("Check local_ai_server logs for actual STT transcripts.")

if __name__ == "__main__":
    asyncio.run(main())
