#!/usr/bin/env python3
"""
Targeted analysis to find the exact segments containing "Hello How are you today"
and test them with optimal parameters for STT processing.
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

def analyze_audio_segment(filepath: str):
    """Detailed analysis of a single audio file"""
    try:
        with open(filepath, "rb") as f:
            audio_data = f.read()
        
        if len(audio_data) == 0:
            return {"status": "empty"}
        
        # Convert to samples
        samples = struct.unpack(f'<{len(audio_data)//2}h', audio_data)
        
        # Calculate detailed statistics
        max_amp = max(abs(s) for s in samples)
        avg_amp = statistics.mean(abs(s) for s in samples)
        rms = (sum(s*s for s in samples) / len(samples)) ** 0.5
        
        # Calculate zero-crossing rate
        zero_crossings = sum(1 for i in range(1, len(samples)) if (samples[i-1] >= 0) != (samples[i] >= 0))
        zcr = zero_crossings / len(samples)
        
        # Calculate energy distribution
        energy_bands = []
        chunk_size = len(samples) // 4
        for i in range(0, len(samples), chunk_size):
            chunk = samples[i:i+chunk_size]
            if chunk:
                chunk_energy = sum(s*s for s in chunk) / len(chunk)
                energy_bands.append(chunk_energy)
        
        # Calculate spectral features
        if len(samples) > 0:
            fft = np.fft.fft(samples)
            freqs = np.fft.fftfreq(len(samples), 1/16000)
            magnitude = np.abs(fft)
            
            # Find dominant frequency
            dominant_freq_idx = np.argmax(magnitude[1:len(magnitude)//2]) + 1
            dominant_freq = abs(freqs[dominant_freq_idx])
            
            # Calculate spectral centroid
            spectral_centroid = np.sum(freqs * magnitude) / np.sum(magnitude) if np.sum(magnitude) > 0 else 0
        else:
            dominant_freq = 0
            spectral_centroid = 0
        
        return {
            "status": "analyzed",
            "size": len(audio_data),
            "samples": len(samples),
            "max_amplitude": max_amp,
            "avg_amplitude": avg_amp,
            "rms": rms,
            "zero_crossing_rate": zcr,
            "dominant_frequency": dominant_freq,
            "spectral_centroid": abs(spectral_centroid),
            "energy_bands": energy_bands,
            "is_speech_like": max_amp > 500 and zcr > 0.05 and dominant_freq > 100
        }
        
    except Exception as e:
        return {"status": "error", "error": str(e)}

def find_high_quality_speech_segments(capture_dir: str):
    """Find segments with the highest speech quality indicators"""
    logging.info(f"🎯 Finding high-quality speech segments in: {capture_dir}")
    
    raw_files = glob.glob(os.path.join(capture_dir, "*.raw"))
    logging.info(f"Found {len(raw_files)} .raw files")
    
    # Analyze all files
    file_analyses = []
    for i, filepath in enumerate(raw_files):
        if i % 200 == 0:
            logging.info(f"Analyzing file {i}/{len(raw_files)}")
        
        analysis = analyze_audio_segment(filepath)
        if analysis["status"] == "analyzed":
            analysis["filepath"] = filepath
            analysis["filename"] = os.path.basename(filepath)
            file_analyses.append(analysis)
    
    # Sort by speech quality indicators
    def speech_quality_score(analysis):
        score = 0
        
        # Amplitude indicators
        if analysis["max_amplitude"] > 2000:
            score += 5
        elif analysis["max_amplitude"] > 1000:
            score += 3
        elif analysis["max_amplitude"] > 500:
            score += 1
        
        # RMS energy
        if analysis["rms"] > 1000:
            score += 3
        elif analysis["rms"] > 500:
            score += 2
        elif analysis["rms"] > 100:
            score += 1
        
        # Zero-crossing rate (speech has higher ZCR)
        if analysis["zero_crossing_rate"] > 0.15:
            score += 3
        elif analysis["zero_crossing_rate"] > 0.1:
            score += 2
        elif analysis["zero_crossing_rate"] > 0.05:
            score += 1
        
        # Frequency content (speech has specific frequency ranges)
        if 200 < analysis["dominant_frequency"] < 3000:
            score += 2
        elif 100 < analysis["dominant_frequency"] < 4000:
            score += 1
        
        # Spectral centroid (speech has higher spectral centroid)
        if analysis["spectral_centroid"] > 1500:
            score += 1
        
        return score
    
    file_analyses.sort(key=speech_quality_score, reverse=True)
    
    # Group high-quality files into segments
    speech_segments = []
    current_segment = []
    segment_id = 0
    
    for file_analysis in file_analyses:
        if speech_quality_score(file_analysis) >= 8:  # High quality threshold
            current_segment.append(file_analysis)
            
            # Create segment when we have enough files
            if len(current_segment) >= 75:  # 1.5 seconds
                segment_info = {
                    "segment_id": segment_id,
                    "files": current_segment,
                    "file_count": len(current_segment),
                    "avg_score": sum(speech_quality_score(f) for f in current_segment) / len(current_segment),
                    "duration_ms": len(current_segment) * 20,
                    "start_file": current_segment[0]["filename"],
                    "end_file": current_segment[-1]["filename"]
                }
                speech_segments.append(segment_info)
                segment_id += 1
                current_segment = []
    
    # Add remaining files
    if len(current_segment) >= 25:
        segment_info = {
            "segment_id": segment_id,
            "files": current_segment,
            "file_count": len(current_segment),
            "avg_score": sum(speech_quality_score(f) for f in current_segment) / len(current_segment),
            "duration_ms": len(current_segment) * 20,
            "start_file": current_segment[0]["filename"],
            "end_file": current_segment[-1]["filename"]
        }
        speech_segments.append(segment_info)
    
    logging.info(f"Found {len(speech_segments)} high-quality speech segments")
    return speech_segments

async def test_optimal_parameters(combined_audio: bytes, segment_info: dict):
    """Test with optimal parameters for STT processing"""
    logging.info(f"🎯 Testing optimal parameters for segment {segment_info['segment_id']}")
    logging.info(f"  Duration: {segment_info['duration_ms']}ms")
    logging.info(f"  Quality score: {segment_info['avg_score']:.2f}")
    
    # Test different approaches
    test_configs = [
        {
            "name": "optimal_chunk",
            "chunk_size": 100,  # 2 seconds
            "resampling": "none",
            "normalization": "aggressive"
        },
        {
            "name": "long_chunk", 
            "chunk_size": 150,  # 3 seconds
            "resampling": "none",
            "normalization": "moderate"
        },
        {
            "name": "very_long_chunk",
            "chunk_size": 200,  # 4 seconds
            "resampling": "none", 
            "normalization": "light"
        },
        {
            "name": "upsampled_chunk",
            "chunk_size": 100,
            "resampling": "upsample_2x",
            "normalization": "aggressive"
        }
    ]
    
    results = []
    
    for config in test_configs:
        logging.info(f"  Testing {config['name']}: {config['chunk_size']} frames")
        
        # Extract chunk from middle of audio
        chunk_start = len(combined_audio) // 2 - (config['chunk_size'] * 640) // 2
        chunk_end = chunk_start + (config['chunk_size'] * 640)
        chunk_audio = combined_audio[chunk_start:chunk_end]
        
        if len(chunk_audio) == 0:
            continue
        
        # Apply resampling if needed
        if config['resampling'] == 'upsample_2x':
            chunk_audio = upsample_2x(chunk_audio)
        
        # Apply normalization
        if config['normalization'] == 'aggressive':
            chunk_audio = aggressive_normalize(chunk_audio)
        elif config['normalization'] == 'moderate':
            chunk_audio = moderate_normalize(chunk_audio)
        elif config['normalization'] == 'light':
            chunk_audio = light_normalize(chunk_audio)
        
        # Test with STT
        result = await test_stt_with_config(
            chunk_audio,
            16000,
            config['name'],
            segment_info
        )
        results.append(result)
        
        # Small delay between tests
        await asyncio.sleep(0.5)
    
    return results

def upsample_2x(audio_data: bytes):
    """2x upsampling by duplicating samples"""
    samples = struct.unpack(f'<{len(audio_data)//2}h', audio_data)
    upsampled = []
    for sample in samples:
        upsampled.extend([sample, sample])
    return struct.pack(f'<{len(upsampled)}h', *upsampled)

def aggressive_normalize(audio_data: bytes):
    """Aggressive normalization for low-volume audio"""
    samples = struct.unpack(f'<{len(audio_data)//2}h', audio_data)
    
    max_amp = max(abs(s) for s in samples)
    if max_amp == 0:
        return audio_data
    
    # Normalize to 90% of max range
    target_max = int(0.9 * 32767)
    normalized = [int(s * target_max / max_amp) for s in samples]
    
    return struct.pack(f'<{len(normalized)}h', *normalized)

def moderate_normalize(audio_data: bytes):
    """Moderate normalization"""
    samples = struct.unpack(f'<{len(audio_data)//2}h', audio_data)
    
    max_amp = max(abs(s) for s in samples)
    if max_amp == 0:
        return audio_data
    
    # Normalize to 70% of max range
    target_max = int(0.7 * 32767)
    normalized = [int(s * target_max / max_amp) for s in samples]
    
    return struct.pack(f'<{len(normalized)}h', *normalized)

def light_normalize(audio_data: bytes):
    """Light normalization"""
    samples = struct.unpack(f'<{len(audio_data)//2}h', audio_data)
    
    max_amp = max(abs(s) for s in samples)
    if max_amp == 0:
        return audio_data
    
    # Normalize to 50% of max range
    target_max = int(0.5 * 32767)
    normalized = [int(s * target_max / max_amp) for s in samples]
    
    return struct.pack(f'<{len(normalized)}h', *normalized)

async def test_stt_with_config(audio_data: bytes, sample_rate: int, config_name: str, segment_info: dict):
    """Test STT with specific configuration"""
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
                response = await asyncio.wait_for(websocket.recv(), timeout=15)
                return {
                    "status": "success",
                    "config_name": config_name,
                    "audio_bytes": len(audio_data),
                    "sample_rate": sample_rate,
                    "tts_bytes": len(response),
                    "segment_id": segment_info['segment_id'],
                    "quality_score": segment_info['avg_score']
                }
            except asyncio.TimeoutError:
                return {
                    "status": "timeout",
                    "config_name": config_name,
                    "audio_bytes": len(audio_data),
                    "sample_rate": sample_rate,
                    "segment_id": segment_info['segment_id']
                }
            except Exception as e:
                return {
                    "status": "error",
                    "config_name": config_name,
                    "error": str(e),
                    "segment_id": segment_info['segment_id']
                }
                
    except Exception as e:
        return {
            "status": "connection_error",
            "config_name": config_name,
            "error": str(e),
            "segment_id": segment_info['segment_id']
        }

async def main():
    logging.info("🎯 TARGETED SPEECH ANALYSIS")
    logging.info("=" * 60)
    logging.info("Finding and testing the exact segments containing 'Hello How are you today'")
    
    # Find capture directory
    capture_dirs = sorted(glob.glob("/app/audio_capture_*/"), reverse=True)
    if not capture_dirs:
        logging.error("No audio capture directories found!")
        return
    
    latest_capture_dir = capture_dirs[0]
    logging.info(f"Using latest capture directory: {latest_capture_dir}")
    
    # Find high-quality speech segments
    speech_segments = find_high_quality_speech_segments(latest_capture_dir)
    
    if not speech_segments:
        logging.error("No high-quality speech segments found!")
        return
    
    # Test top 3 segments with optimal parameters
    test_segments = speech_segments[:3]
    all_results = []
    
    for segment_info in test_segments:
        logging.info(f"\n🎯 Testing segment {segment_info['segment_id']}")
        logging.info(f"  Files: {segment_info['file_count']}")
        logging.info(f"  Duration: {segment_info['duration_ms']}ms")
        logging.info(f"  Quality: {segment_info['avg_score']:.2f}")
        
        # Combine audio
        combined_audio = b""
        for file_analysis in segment_info['files']:
            try:
                with open(file_analysis['filepath'], "rb") as f:
                    audio_data = f.read()
                    combined_audio += audio_data
            except Exception as e:
                logging.warning(f"Error reading {file_analysis['filepath']}: {e}")
                continue
        
        if len(combined_audio) == 0:
            logging.warning("No audio data in segment")
            continue
        
        # Test with optimal parameters
        segment_results = await test_optimal_parameters(combined_audio, segment_info)
        all_results.extend(segment_results)
        
        await asyncio.sleep(1.0)
    
    # Analyze results
    logging.info("\n📊 TARGETED ANALYSIS RESULTS")
    logging.info("=" * 60)
    
    successful = [r for r in all_results if r["status"] == "success"]
    timeouts = [r for r in all_results if r["status"] == "timeout"]
    errors = [r for r in all_results if r["status"] in ["error", "connection_error"]]
    
    logging.info(f"Total tests: {len(all_results)}")
    logging.info(f"Successful: {len(successful)} ({len(successful)/len(all_results)*100:.1f}%)")
    logging.info(f"Timeouts: {len(timeouts)} ({len(timeouts)/len(all_results)*100:.1f}%)")
    logging.info(f"Errors: {len(errors)} ({len(errors)/len(all_results)*100:.1f}%)")
    
    if successful:
        logging.info("\n✅ SUCCESSFUL CONFIGURATIONS:")
        for result in successful:
            logging.info(f"  {result['config_name']}: {result['audio_bytes']} bytes → {result['tts_bytes']} bytes TTS")
            logging.info(f"    Segment {result['segment_id']}, Quality: {result['quality_score']:.2f}")
    
    # Group by configuration
    config_results = defaultdict(list)
    for result in all_results:
        config_results[result["config_name"]].append(result)
    
    logging.info("\n📈 RESULTS BY CONFIGURATION:")
    for config_name in sorted(config_results.keys()):
        results = config_results[config_name]
        success_count = sum(1 for r in results if r["status"] == "success")
        logging.info(f"  {config_name}: {success_count}/{len(results)} successful")
    
    logging.info("\n✅ Targeted analysis complete!")
    logging.info("Check local_ai_server logs for STT transcripts from successful tests.")

if __name__ == "__main__":
    asyncio.run(main())
