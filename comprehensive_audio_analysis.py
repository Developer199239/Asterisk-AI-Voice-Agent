#!/usr/bin/env python3
"""
Comprehensive audio analysis to find correct parameters for VAD, resampling, and STT.
This will analyze the captured audio files to find the exact segments containing
"Hello How are you today" and determine optimal processing parameters.
"""

import os
import glob
import struct
import logging
import statistics
import asyncio
import websockets
import base64
import json
import time
from collections import defaultdict
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

LOCAL_AI_SERVER_URL = "ws://localhost:8765/ws"

def analyze_audio_quality(filepath: str):
    """Analyze audio quality and content of a single file"""
    try:
        with open(filepath, "rb") as f:
            audio_data = f.read()
        
        if len(audio_data) == 0:
            return {"status": "empty", "size": 0}
        
        # Convert bytes to 16-bit signed integers
        samples = struct.unpack(f'<{len(audio_data)//2}h', audio_data)
        
        # Calculate audio statistics
        max_amplitude = max(abs(s) for s in samples)
        avg_amplitude = statistics.mean(abs(s) for s in samples)
        rms = (sum(s*s for s in samples) / len(samples)) ** 0.5
        
        # Calculate dynamic range
        min_val = min(samples)
        max_val = max(samples)
        dynamic_range = max_val - min_val
        
        # Check for silence
        silence_threshold = 100
        is_silence = max_amplitude < silence_threshold
        
        # Check for constant values (noise/corruption)
        unique_values = len(set(samples))
        is_constant = unique_values < 10
        
        # Calculate zero-crossing rate (indicator of speech activity)
        zero_crossings = sum(1 for i in range(1, len(samples)) if (samples[i-1] >= 0) != (samples[i] >= 0))
        zcr = zero_crossings / len(samples)
        
        # Calculate spectral centroid (rough frequency content indicator)
        if len(samples) > 0:
            # Simple spectral analysis
            fft = np.fft.fft(samples)
            freqs = np.fft.fftfreq(len(samples), 1/16000)  # 16kHz sample rate
            magnitude = np.abs(fft)
            spectral_centroid = np.sum(freqs * magnitude) / np.sum(magnitude) if np.sum(magnitude) > 0 else 0
        else:
            spectral_centroid = 0
        
        return {
            "status": "analyzed",
            "size": len(audio_data),
            "samples": len(samples),
            "max_amplitude": max_amplitude,
            "avg_amplitude": avg_amplitude,
            "rms": rms,
            "dynamic_range": dynamic_range,
            "is_silence": is_silence,
            "is_constant": is_constant,
            "unique_values": unique_values,
            "zero_crossing_rate": zcr,
            "spectral_centroid": abs(spectral_centroid),
            "first_10_samples": samples[:10],
            "last_10_samples": samples[-10:]
        }
        
    except Exception as e:
        return {"status": "error", "error": str(e)}

def find_speech_segments(capture_dir: str):
    """Find segments most likely to contain speech based on audio analysis"""
    logging.info(f"🔍 Finding speech segments in: {capture_dir}")
    
    raw_files = glob.glob(os.path.join(capture_dir, "*.raw"))
    logging.info(f"Found {len(raw_files)} .raw files")
    
    if not raw_files:
        logging.error("No audio files found!")
        return []
    
    # Analyze all files for speech characteristics
    speech_scores = []
    
    for i, filepath in enumerate(raw_files):
        if i % 100 == 0:  # Progress indicator
            logging.info(f"Analyzing file {i}/{len(raw_files)}")
        
        result = analyze_audio_quality(filepath)
        if result["status"] == "analyzed":
            # Calculate speech likelihood score
            score = 0
            
            # Higher amplitude = more likely speech
            if result["max_amplitude"] > 1000:
                score += 3
            elif result["max_amplitude"] > 500:
                score += 2
            elif result["max_amplitude"] > 100:
                score += 1
            
            # Higher RMS = more energy
            if result["rms"] > 1000:
                score += 2
            elif result["rms"] > 500:
                score += 1
            
            # Higher zero-crossing rate = more speech-like
            if result["zero_crossing_rate"] > 0.1:
                score += 2
            elif result["zero_crossing_rate"] > 0.05:
                score += 1
            
            # Higher spectral centroid = more high-frequency content
            if result["spectral_centroid"] > 2000:
                score += 1
            
            # Penalize silence and constant values
            if result["is_silence"]:
                score = 0
            if result["is_constant"]:
                score = 0
            
            speech_scores.append({
                "filepath": filepath,
                "filename": os.path.basename(filepath),
                "score": score,
                "max_amplitude": result["max_amplitude"],
                "rms": result["rms"],
                "zero_crossing_rate": result["zero_crossing_rate"],
                "spectral_centroid": result["spectral_centroid"]
            })
    
    # Sort by speech score
    speech_scores.sort(key=lambda x: x["score"], reverse=True)
    
    # Group high-scoring files into segments
    speech_segments = []
    current_segment = []
    segment_id = 0
    
    for file_info in speech_scores:
        if file_info["score"] >= 3:  # High speech likelihood
            current_segment.append(file_info)
            
            # When we have 50-100 files (1-2 seconds), create a segment
            if len(current_segment) >= 50:
                segment_info = {
                    "segment_id": segment_id,
                    "files": current_segment,
                    "file_count": len(current_segment),
                    "avg_score": sum(f["score"] for f in current_segment) / len(current_segment),
                    "total_duration_ms": len(current_segment) * 20,  # 20ms per frame
                    "start_file": current_segment[0]["filename"],
                    "end_file": current_segment[-1]["filename"]
                }
                speech_segments.append(segment_info)
                segment_id += 1
                current_segment = []
    
    # Add remaining files as final segment
    if len(current_segment) >= 20:
        segment_info = {
            "segment_id": segment_id,
            "files": current_segment,
            "file_count": len(current_segment),
            "avg_score": sum(f["score"] for f in current_segment) / len(current_segment),
            "total_duration_ms": len(current_segment) * 20,
            "start_file": current_segment[0]["filename"],
            "end_file": current_segment[-1]["filename"]
        }
        speech_segments.append(segment_info)
    
    logging.info(f"Found {len(speech_segments)} high-quality speech segments")
    return speech_segments

async def test_different_chunk_sizes(combined_audio: bytes, segment_info: dict):
    """Test different chunk sizes and resampling approaches"""
    logging.info(f"🧪 Testing different processing approaches for segment {segment_info['segment_id']}")
    
    # Test different chunk sizes (in frames)
    chunk_sizes = [25, 50, 100, 150, 200]  # 0.5s to 4s
    results = []
    
    for chunk_size in chunk_sizes:
        # Extract chunk from the middle of the audio
        chunk_start = len(combined_audio) // 2 - (chunk_size * 640) // 2
        chunk_end = chunk_start + (chunk_size * 640)
        chunk_audio = combined_audio[chunk_start:chunk_end]
        
        if len(chunk_audio) == 0:
            continue
        
        logging.info(f"  Testing chunk size {chunk_size} frames ({len(chunk_audio)} bytes)")
        
        # Test with different resampling approaches
        resampling_tests = [
            {"name": "no_resample", "rate": 16000, "audio": chunk_audio},
            {"name": "upsample_2x", "rate": 16000, "audio": upsample_2x(chunk_audio)},
            {"name": "normalize", "rate": 16000, "audio": normalize_audio(chunk_audio)},
        ]
        
        for test in resampling_tests:
            result = await test_stt_with_approach(
                test["audio"], 
                test["rate"], 
                f"chunk_{chunk_size}_{test['name']}"
            )
            result["chunk_size"] = chunk_size
            result["resampling"] = test["name"]
            result["segment_info"] = segment_info
            results.append(result)
    
    return results

def upsample_2x(audio_data: bytes):
    """Simple 2x upsampling by duplicating samples"""
    samples = struct.unpack(f'<{len(audio_data)//2}h', audio_data)
    upsampled = []
    for sample in samples:
        upsampled.extend([sample, sample])
    return struct.pack(f'<{len(upsampled)}h', *upsampled)

def normalize_audio(audio_data: bytes):
    """Normalize audio to improve STT detection"""
    samples = struct.unpack(f'<{len(audio_data)//2}h', audio_data)
    
    # Find max amplitude
    max_amp = max(abs(s) for s in samples)
    if max_amp == 0:
        return audio_data
    
    # Normalize to 80% of max range
    target_max = int(0.8 * 32767)
    normalized = [int(s * target_max / max_amp) for s in samples]
    
    return struct.pack(f'<{len(normalized)}h', *normalized)

async def test_stt_with_approach(audio_data: bytes, sample_rate: int, test_name: str):
    """Test STT with specific audio data and parameters"""
    try:
        msg = json.dumps({
            "type": "audio", 
            "data": base64.b64encode(audio_data).decode('utf-8'),
            "rate": sample_rate,
            "format": "pcm16le"
        })
        
        async with websockets.connect(LOCAL_AI_SERVER_URL) as websocket:
            await websocket.send(msg)
            
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=10)
                return {
                    "status": "success",
                    "test_name": test_name,
                    "audio_bytes": len(audio_data),
                    "sample_rate": sample_rate,
                    "tts_bytes": len(response)
                }
            except asyncio.TimeoutError:
                return {
                    "status": "timeout",
                    "test_name": test_name,
                    "audio_bytes": len(audio_data),
                    "sample_rate": sample_rate
                }
            except Exception as e:
                return {
                    "status": "error",
                    "test_name": test_name,
                    "error": str(e),
                    "audio_bytes": len(audio_data),
                    "sample_rate": sample_rate
                }
                
    except Exception as e:
        return {
            "status": "connection_error",
            "test_name": test_name,
            "error": str(e)
        }

async def comprehensive_test(capture_dir: str):
    """Run comprehensive audio analysis and testing"""
    logging.info("🎯 COMPREHENSIVE AUDIO ANALYSIS")
    logging.info("=" * 60)
    logging.info("Finding optimal parameters for VAD, resampling, and STT")
    
    # Find speech segments
    speech_segments = find_speech_segments(capture_dir)
    
    if not speech_segments:
        logging.error("No speech segments found!")
        return
    
    logging.info(f"Found {len(speech_segments)} speech segments")
    
    # Test top 3 speech segments
    test_segments = speech_segments[:3]
    all_results = []
    
    for segment_info in test_segments:
        logging.info(f"\n🔍 Testing speech segment {segment_info['segment_id']}")
        logging.info(f"  Files: {segment_info['file_count']}")
        logging.info(f"  Duration: {segment_info['total_duration_ms']}ms")
        logging.info(f"  Avg score: {segment_info['avg_score']:.2f}")
        
        # Combine audio from this segment
        combined_audio = b""
        for file_info in segment_info['files']:
            try:
                with open(file_info['filepath'], "rb") as f:
                    audio_data = f.read()
                    combined_audio += audio_data
            except Exception as e:
                logging.warning(f"Error reading {file_info['filepath']}: {e}")
                continue
        
        if len(combined_audio) == 0:
            logging.warning("No audio data in segment")
            continue
        
        # Test different chunk sizes and resampling
        segment_results = await test_different_chunk_sizes(combined_audio, segment_info)
        all_results.extend(segment_results)
        
        # Small delay between segments
        await asyncio.sleep(1.0)
    
    # Analyze results
    logging.info("\n📊 COMPREHENSIVE TEST RESULTS")
    logging.info("=" * 60)
    
    successful_tests = [r for r in all_results if r["status"] == "success"]
    timeout_tests = [r for r in all_results if r["status"] == "timeout"]
    error_tests = [r for r in all_results if r["status"] in ["error", "connection_error"]]
    
    logging.info(f"Total tests: {len(all_results)}")
    logging.info(f"Successful: {len(successful_tests)} ({len(successful_tests)/len(all_results)*100:.1f}%)")
    logging.info(f"Timeouts: {len(timeout_tests)} ({len(timeout_tests)/len(all_results)*100:.1f}%)")
    logging.info(f"Errors: {len(error_tests)} ({len(error_tests)/len(all_results)*100:.1f}%)")
    
    if successful_tests:
        logging.info("\n✅ SUCCESSFUL TESTS:")
        for result in successful_tests:
            logging.info(f"  {result['test_name']}: {result['audio_bytes']} bytes, {result['sample_rate']}Hz → {result['tts_bytes']} bytes TTS")
    
    # Group by chunk size
    chunk_results = defaultdict(list)
    for result in all_results:
        if "chunk_size" in result:
            chunk_results[result["chunk_size"]].append(result)
    
    logging.info("\n📈 RESULTS BY CHUNK SIZE:")
    for chunk_size in sorted(chunk_results.keys()):
        results = chunk_results[chunk_size]
        success_count = sum(1 for r in results if r["status"] == "success")
        logging.info(f"  {chunk_size} frames: {success_count}/{len(results)} successful")
    
    logging.info("\n✅ Comprehensive analysis complete!")
    logging.info("Check local_ai_server logs for STT transcripts from successful tests.")

def main():
    # Find the latest capture directory
    capture_dirs = sorted(glob.glob("/app/audio_capture_*/"), reverse=True)
    if not capture_dirs:
        logging.error("No audio capture directories found!")
        return
    
    latest_capture_dir = capture_dirs[0]
    logging.info(f"Using latest capture directory: {latest_capture_dir}")
    
    # Run comprehensive analysis
    asyncio.run(comprehensive_test(latest_capture_dir))

if __name__ == "__main__":
    main()
