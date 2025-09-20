#!/usr/bin/env python3
"""
Test optimized Vosk configuration for better telephony accuracy
"""

import asyncio
import websockets
import base64
import json
import logging
import os
import glob
import time
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

LOCAL_AI_SERVER_URL = "ws://localhost:8765/ws"

def find_best_audio_segments(capture_dir: str, max_segments: int = 3):
    """Find the best audio segments for testing"""
    logging.info(f"🔍 Finding best audio segments in: {capture_dir}")
    
    raw_files = glob.glob(os.path.join(capture_dir, "*.raw"))
    logging.info(f"Found {len(raw_files)} .raw files")
    
    if not raw_files:
        logging.error("No audio files found!")
        return []
    
    # Group files by type and find segments
    file_groups = defaultdict(list)
    
    for filepath in sorted(raw_files):
        filename = os.path.basename(filepath)
        parts = filename.split('_')
        if len(parts) >= 4:
            file_type = f"{parts[2]}_{parts[3]}"
        else:
            file_type = "unknown"
        file_groups[file_type].append(filepath)
    
    # Create segments from each group
    segments = []
    for file_type, files in file_groups.items():
        logging.info(f"Processing {file_type} files...")
        
        # Group into different segment sizes for testing
        for segment_size in [50, 100, 150, 200]:  # 1s, 2s, 3s, 4s
            for i in range(0, len(files), segment_size):
                segment_files = files[i:i+segment_size]
                if len(segment_files) >= 25:  # At least 0.5 seconds
                    segments.append({
                        "type": file_type,
                        "files": segment_files,
                        "file_count": len(segment_files),
                        "duration_ms": len(segment_files) * 20,
                        "segment_size": segment_size
                    })
    
    # Sort by duration (longer segments first)
    segments.sort(key=lambda x: x["duration_ms"], reverse=True)
    
    logging.info(f"Found {len(segments)} audio segments")
    return segments[:max_segments]

def preprocess_audio(audio_data: bytes, method: str = "normalize") -> bytes:
    """Preprocess audio data for better STT accuracy"""
    try:
        import struct
        import numpy as np
        
        # Convert bytes to 16-bit signed integers
        samples = struct.unpack(f'<{len(audio_data)//2}h', audio_data)
        samples = np.array(samples, dtype=np.float32)
        
        if method == "normalize":
            # Normalize to improve signal quality
            max_val = np.max(np.abs(samples))
            if max_val > 0:
                samples = samples / max_val * 0.8  # Normalize to 80% of max range
        
        elif method == "amplify":
            # Amplify quiet audio
            rms = np.sqrt(np.mean(samples**2))
            if rms > 0:
                amplification = 0.1 / rms  # Target RMS of 0.1
                samples = samples * min(amplification, 10.0)  # Cap amplification at 10x
        
        elif method == "noise_reduce":
            # Simple noise reduction (high-pass filter)
            if len(samples) > 1:
                # Simple high-pass filter to remove low-frequency noise
                filtered = np.zeros_like(samples)
                filtered[0] = samples[0]
                for i in range(1, len(samples)):
                    filtered[i] = 0.95 * filtered[i-1] + samples[i] - samples[i-1]
                samples = filtered
        
        # Convert back to 16-bit integers
        samples = np.clip(samples, -1.0, 1.0)
        samples = (samples * 32767).astype(np.int16)
        
        return struct.pack(f'<{len(samples)}h', *samples)
        
    except Exception as e:
        logging.error(f"Error preprocessing audio: {e}")
        return audio_data

async def test_stt_with_preprocessing(combined_audio: bytes, segment_info: dict, preprocessing: str = "none") -> dict:
    """Test STT with different preprocessing methods"""
    logging.info(f"🧪 Testing STT with {preprocessing} preprocessing")
    
    # Apply preprocessing
    if preprocessing != "none":
        processed_audio = preprocess_audio(combined_audio, preprocessing)
    else:
        processed_audio = combined_audio
    
    try:
        msg = json.dumps({
            "type": "audio", 
            "data": base64.b64encode(processed_audio).decode('utf-8'),
            "rate": 16000,
            "format": "pcm16le"
        })
        
        async with websockets.connect(LOCAL_AI_SERVER_URL) as websocket:
            await websocket.send(msg)
            
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=15)
                return {
                    "status": "success",
                    "preprocessing": preprocessing,
                    "audio_bytes": len(processed_audio),
                    "tts_bytes": len(response),
                    "segment_info": segment_info
                }
            except asyncio.TimeoutError:
                return {
                    "status": "timeout",
                    "preprocessing": preprocessing,
                    "segment_info": segment_info
                }
            except Exception as e:
                return {
                    "status": "error",
                    "preprocessing": preprocessing,
                    "error": str(e),
                    "segment_info": segment_info
                }
                
    except Exception as e:
        return {
            "status": "connection_error",
            "preprocessing": preprocessing,
            "error": str(e),
            "segment_info": segment_info
        }

async def test_different_approaches(capture_dir: str):
    """Test different approaches to improve STT accuracy"""
    logging.info("🎯 OPTIMIZED VOSK TESTING")
    logging.info("=" * 60)
    logging.info("Testing different preprocessing approaches with Vosk")
    
    # Find best audio segments
    segments = find_best_audio_segments(capture_dir, max_segments=2)
    
    if not segments:
        logging.error("No audio segments found!")
        return
    
    # Test different preprocessing methods
    preprocessing_methods = ["none", "normalize", "amplify", "noise_reduce"]
    
    all_results = []
    
    for i, segment_info in enumerate(segments):
        logging.info(f"\n🔍 Testing segment {i+1}/{len(segments)}")
        logging.info(f"  Type: {segment_info['type']}")
        logging.info(f"  Files: {segment_info['file_count']}")
        logging.info(f"  Duration: {segment_info['duration_ms']}ms")
        
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
            logging.warning("No audio data in segment")
            continue
        
        # Test each preprocessing method
        for method in preprocessing_methods:
            logging.info(f"  Testing {method} preprocessing...")
            result = await test_stt_with_preprocessing(combined_audio, segment_info, method)
            all_results.append(result)
            
            # Small delay between tests
            await asyncio.sleep(1.0)
        
        # Delay between segments
        await asyncio.sleep(2.0)
    
    # Analyze results
    logging.info("\n📊 PREPROCESSING RESULTS")
    logging.info("=" * 60)
    
    # Group by preprocessing method
    method_results = defaultdict(list)
    for result in all_results:
        method_results[result["preprocessing"]].append(result)
    
    for method, results in method_results.items():
        successful = sum(1 for r in results if r["status"] == "success")
        timeouts = sum(1 for r in results if r["status"] == "timeout")
        errors = sum(1 for r in results if r["status"] in ["error", "connection_error"])
        total = len(results)
        
        logging.info(f"\n{method.upper()}:")
        logging.info(f"  Total tests: {total}")
        logging.info(f"  Successful: {successful} ({successful/total*100:.1f}%)")
        logging.info(f"  Timeouts: {timeouts} ({timeouts/total*100:.1f}%)")
        logging.info(f"  Errors: {errors} ({errors/total*100:.1f}%)")
        
        if successful > 0:
            avg_tts_bytes = sum(r.get("tts_bytes", 0) for r in results if r["status"] == "success") / successful
            logging.info(f"  Average TTS response: {avg_tts_bytes:.0f} bytes")
    
    # Find best method
    best_method = None
    best_success_rate = 0
    
    for method, results in method_results.items():
        success_rate = sum(1 for r in results if r["status"] == "success") / len(results) if results else 0
        if success_rate > best_success_rate:
            best_success_rate = success_rate
            best_method = method
    
    logging.info(f"\n🏆 BEST PREPROCESSING METHOD: {best_method.upper()}")
    logging.info(f"  Success rate: {best_success_rate*100:.1f}%")
    
    logging.info("\n✅ Testing complete!")
    logging.info("Check local_ai_server logs for actual STT transcripts.")

async def main():
    # Find the latest capture directory
    capture_dirs = sorted(glob.glob("/app/audio_capture_*/"), reverse=True)
    if not capture_dirs:
        logging.error("No audio capture directories found!")
        return
    
    latest_capture_dir = capture_dirs[0]
    logging.info(f"Using latest capture directory: {latest_capture_dir}")
    
    # Run testing
    await test_different_approaches(latest_capture_dir)

if __name__ == "__main__":
    asyncio.run(main())
