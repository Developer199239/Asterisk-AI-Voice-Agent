#!/usr/bin/env python3
"""
Test specific segments of captured audio to find the best quality segments
and analyze STT accuracy patterns.
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

def find_speech_segments(capture_dir: str):
    """Find segments that are most likely to contain speech based on file patterns"""
    logging.info(f"Analyzing captured audio for speech segments in: {capture_dir}")
    
    raw_files = glob.glob(os.path.join(capture_dir, "*.raw"))
    logging.info(f"Found {len(raw_files)} .raw files")
    
    # Group files by type and analyze patterns
    file_groups = defaultdict(list)
    
    for filepath in sorted(raw_files):
        filename = os.path.basename(filepath)
        parts = filename.split('_')
        if len(parts) >= 4:
            file_type = f"{parts[2]}_{parts[3]}"
        else:
            file_type = "unknown"
        file_groups[file_type].append(filepath)
    
    # Find segments that are likely to contain speech
    # Look for segments with consistent file sizes (not silence)
    speech_segments = []
    
    for file_type, files in file_groups.items():
        logging.info(f"Analyzing {file_type} files...")
        
        # Group into 2-second segments (100 files = 2 seconds)
        for i in range(0, len(files), 100):
            segment_files = files[i:i+100]
            if len(segment_files) < 50:  # Skip segments with too few files
                continue
                
            # Analyze file sizes in this segment
            sizes = []
            for filepath in segment_files:
                try:
                    size = os.path.getsize(filepath)
                    sizes.append(size)
                except:
                    continue
            
            if not sizes:
                continue
                
            # Calculate statistics
            avg_size = sum(sizes) / len(sizes)
            min_size = min(sizes)
            max_size = max(sizes)
            variance = sum((s - avg_size) ** 2 for s in sizes) / len(sizes)
            
            # Look for segments with consistent, non-zero audio
            if avg_size > 600 and variance < 1000:  # Consistent ~640 byte files
                segment_info = {
                    "type": file_type,
                    "segment_id": len(speech_segments),
                    "file_count": len(segment_files),
                    "avg_size": avg_size,
                    "variance": variance,
                    "files": segment_files[:10],  # First 10 files for reference
                    "start_time": i * 20,  # Approximate start time in ms
                }
                speech_segments.append(segment_info)
                logging.info(f"  Found potential speech segment {len(speech_segments)}: {len(segment_files)} files, avg_size={avg_size:.1f}, variance={variance:.1f}")
    
    logging.info(f"Found {len(speech_segments)} potential speech segments")
    return speech_segments

async def test_speech_segment(segment_info: dict):
    """Test a specific speech segment with STT"""
    logging.info(f"Testing speech segment {segment_info['segment_id']}: {segment_info['file_count']} files, avg_size={segment_info['avg_size']:.1f}")
    
    # Combine audio from this segment
    combined_audio = b""
    for filepath in segment_info['files']:
        try:
            with open(filepath, "rb") as f:
                audio_data = f.read()
                combined_audio += audio_data
        except Exception as e:
            logging.warning(f"Error reading {filepath}: {e}")
            continue
    
    if len(combined_audio) == 0:
        return {
            "status": "no_audio",
            "segment_info": segment_info
        }
    
    # Test with STT using AI engine approach
    try:
        msg = json.dumps({
            "type": "audio", 
            "data": base64.b64encode(combined_audio).decode('utf-8'),
            "rate": 16000,
            "format": "pcm16le"
        })
        
        async with websockets.connect(LOCAL_AI_SERVER_URL) as websocket:
            await websocket.send(msg)
            logging.info(f"✅ Sent {len(combined_audio)} bytes to STT")
            
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=10)
                logging.info(f"✅ Received TTS response: {len(response)} bytes")
                
                return {
                    "status": "success",
                    "audio_bytes_sent": len(combined_audio),
                    "tts_bytes_received": len(response),
                    "segment_info": segment_info
                }
                
            except asyncio.TimeoutError:
                return {
                    "status": "timeout",
                    "segment_info": segment_info
                }
            except Exception as e:
                return {
                    "status": "response_error",
                    "error": str(e),
                    "segment_info": segment_info
                }
                
    except Exception as e:
        return {
            "status": "connection_error",
            "error": str(e),
            "segment_info": segment_info
        }

async def main():
    logging.info("🎤 SPEECH SEGMENT ANALYSIS")
    logging.info("=" * 50)
    logging.info("Finding and testing segments most likely to contain speech")
    
    # Find the latest capture directory
    capture_dirs = sorted(glob.glob("/app/audio_capture_*/"), reverse=True)
    if not capture_dirs:
        logging.error("No audio capture directories found!")
        return
    
    latest_capture_dir = capture_dirs[0]
    logging.info(f"Using latest capture directory: {latest_capture_dir}")
    
    # Find speech segments
    speech_segments = find_speech_segments(latest_capture_dir)
    
    if not speech_segments:
        logging.error("No speech segments found!")
        return
    
    # Test the best speech segments
    logging.info(f"\n🧪 TESTING TOP SPEECH SEGMENTS")
    logging.info("=" * 50)
    
    # Test up to 5 segments
    test_segments = speech_segments[:5]
    results = []
    
    for i, segment_info in enumerate(test_segments):
        logging.info(f"\n--- Testing speech segment {i+1}/{len(test_segments)} ---")
        result = await test_speech_segment(segment_info)
        results.append(result)
        await asyncio.sleep(1.0)
    
    # Print results
    logging.info("\n📋 SPEECH SEGMENT TEST RESULTS")
    logging.info("=" * 50)
    
    success = sum(1 for r in results if r["status"] == "success")
    total = len(results)
    
    logging.info(f"Successfully tested: {success}/{total} segments")
    
    if success > 0:
        logging.info("\n✅ Successful segments:")
        for result in results:
            if result["status"] == "success":
                seg = result["segment_info"]
                logging.info(f"  Segment {seg['segment_id']}: {seg['file_count']} files, avg_size={seg['avg_size']:.1f}")
                logging.info(f"    Audio sent: {result['audio_bytes_sent']} bytes")
                logging.info(f"    TTS received: {result['tts_bytes_received']} bytes")
    
    logging.info("\n✅ Testing complete!")
    logging.info("Check local_ai_server logs for STT transcripts from these segments.")

if __name__ == "__main__":
    asyncio.run(main())
