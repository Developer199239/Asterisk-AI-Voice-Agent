#!/usr/bin/env python3
"""
Test Faster-Whisper vs Vosk on captured telephony audio
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

def find_best_audio_segments(capture_dir: str, max_segments: int = 5):
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
        
        # Group into 2-second segments (100 files = 2 seconds)
        for i in range(0, len(files), 100):
            segment_files = files[i:i+100]
            if len(segment_files) >= 50:  # At least 1 second
                segments.append({
                    "type": file_type,
                    "files": segment_files,
                    "file_count": len(segment_files),
                    "duration_ms": len(segment_files) * 20
                })
    
    # Sort by file count (longer segments first)
    segments.sort(key=lambda x: x["file_count"], reverse=True)
    
    logging.info(f"Found {len(segments)} audio segments")
    return segments[:max_segments]

async def test_stt_provider(combined_audio: bytes, segment_info: dict, provider_name: str):
    """Test STT with a specific provider"""
    logging.info(f"🧪 Testing {provider_name} with {segment_info['file_count']} files, {segment_info['duration_ms']}ms")
    
    try:
        msg = json.dumps({
            "type": "audio", 
            "data": base64.b64encode(combined_audio).decode('utf-8'),
            "rate": 16000,
            "format": "pcm16le"
        })
        
        async with websockets.connect(LOCAL_AI_SERVER_URL) as websocket:
            await websocket.send(msg)
            
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=15)
                return {
                    "status": "success",
                    "provider": provider_name,
                    "audio_bytes": len(combined_audio),
                    "tts_bytes": len(response),
                    "segment_info": segment_info
                }
            except asyncio.TimeoutError:
                return {
                    "status": "timeout",
                    "provider": provider_name,
                    "segment_info": segment_info
                }
            except Exception as e:
                return {
                    "status": "error",
                    "provider": provider_name,
                    "error": str(e),
                    "segment_info": segment_info
                }
                
    except Exception as e:
        return {
            "status": "connection_error",
            "provider": provider_name,
            "error": str(e),
            "segment_info": segment_info
        }

async def compare_stt_providers(capture_dir: str):
    """Compare Vosk vs Faster-Whisper on captured audio"""
    logging.info("🎯 STT PROVIDER COMPARISON")
    logging.info("=" * 60)
    logging.info("Comparing Vosk vs Faster-Whisper on captured telephony audio")
    
    # Find best audio segments
    segments = find_best_audio_segments(capture_dir, max_segments=3)
    
    if not segments:
        logging.error("No audio segments found!")
        return
    
    # Test each segment with both providers
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
        
        # Test with Vosk (current provider)
        logging.info("  Testing with Vosk...")
        vosk_result = await test_stt_provider(combined_audio, segment_info, "vosk")
        all_results.append(vosk_result)
        
        # Small delay between tests
        await asyncio.sleep(1.0)
        
        # Test with Faster-Whisper (if available)
        logging.info("  Testing with Faster-Whisper...")
        faster_whisper_result = await test_stt_provider(combined_audio, segment_info, "faster_whisper")
        all_results.append(faster_whisper_result)
        
        # Delay between segments
        await asyncio.sleep(2.0)
    
    # Analyze results
    logging.info("\n📊 COMPARISON RESULTS")
    logging.info("=" * 60)
    
    # Group by provider
    provider_results = defaultdict(list)
    for result in all_results:
        provider_results[result["provider"]].append(result)
    
    for provider, results in provider_results.items():
        successful = sum(1 for r in results if r["status"] == "success")
        timeouts = sum(1 for r in results if r["status"] == "timeout")
        errors = sum(1 for r in results if r["status"] in ["error", "connection_error"])
        total = len(results)
        
        logging.info(f"\n{provider.upper()}:")
        logging.info(f"  Total tests: {total}")
        logging.info(f"  Successful: {successful} ({successful/total*100:.1f}%)")
        logging.info(f"  Timeouts: {timeouts} ({timeouts/total*100:.1f}%)")
        logging.info(f"  Errors: {errors} ({errors/total*100:.1f}%)")
        
        if successful > 0:
            avg_tts_bytes = sum(r.get("tts_bytes", 0) for r in results if r["status"] == "success") / successful
            logging.info(f"  Average TTS response: {avg_tts_bytes:.0f} bytes")
    
    # Overall comparison
    vosk_success = sum(1 for r in all_results if r["provider"] == "vosk" and r["status"] == "success")
    faster_whisper_success = sum(1 for r in all_results if r["provider"] == "faster_whisper" and r["status"] == "success")
    
    logging.info(f"\n🏆 OVERALL COMPARISON:")
    logging.info(f"  Vosk success rate: {vosk_success}/{len(segments)} ({vosk_success/len(segments)*100:.1f}%)")
    logging.info(f"  Faster-Whisper success rate: {faster_whisper_success}/{len(segments)} ({faster_whisper_success/len(segments)*100:.1f}%)")
    
    if faster_whisper_success > vosk_success:
        logging.info("  🎉 Faster-Whisper performs better!")
    elif vosk_success > faster_whisper_success:
        logging.info("  🎉 Vosk performs better!")
    else:
        logging.info("  🤝 Both providers perform similarly")
    
    logging.info("\n✅ Comparison complete!")
    logging.info("Check local_ai_server logs for actual STT transcripts from both providers.")

async def main():
    # Find the latest capture directory
    capture_dirs = sorted(glob.glob("/app/audio_capture_*/"), reverse=True)
    if not capture_dirs:
        logging.error("No audio capture directories found!")
        return
    
    latest_capture_dir = capture_dirs[0]
    logging.info(f"Using latest capture directory: {latest_capture_dir}")
    
    # Run comparison
    await compare_stt_providers(latest_capture_dir)

if __name__ == "__main__":
    asyncio.run(main())
