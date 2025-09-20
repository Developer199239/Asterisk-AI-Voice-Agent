#!/usr/bin/env python3
"""
Test captured audio files with STT to analyze speech detection and transcription accuracy.
This script will test the 2,113 captured audio files from the test call.
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

async def test_stt_file(filepath: str, file_info: dict):
    """Test a single audio file with STT"""
    logging.info(f"Testing file: {os.path.basename(filepath)}")
    
    try:
        with open(filepath, "rb") as f:
            audio_data = f.read()
        
        # All captured files should be 640 bytes (20ms of 16kHz PCM)
        expected_size = 640
        if len(audio_data) != expected_size:
            logging.warning(f"Unexpected file size: {len(audio_data)} bytes (expected {expected_size})")
        
        # Test with STT
        async with websockets.connect(LOCAL_AI_SERVER_URL) as websocket:
            # Send audio data
            msg = json.dumps({
                "type": "audio",
                "data": base64.b64encode(audio_data).decode('utf-8'),
                "rate": 16000,
                "format": "pcm16le"
            })
            await websocket.send(msg)
            
            # Wait for response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5)
                # Response is binary TTS audio, not JSON transcript
                # We need to check logs for the actual STT transcript
                return {
                    "status": "processed",
                    "response_size": len(response),
                    "file_info": file_info
                }
            except asyncio.TimeoutError:
                return {
                    "status": "timeout",
                    "file_info": file_info
                }
            except Exception as e:
                logging.error(f"WebSocket error for {file_info['filename']}: {e}")
                return {
                    "status": "error",
                    "error": str(e),
                    "file_info": file_info
                }
                
    except Exception as e:
        logging.error(f"File error for {file_info['filename']}: {e}")
        return {
            "status": "file_error",
            "error": str(e),
            "file_info": file_info
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
        
        # Parse filename: 0001_rtp_ssrc_230021204_raw_rtp_all_220807_622.raw
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

async def test_sample_files(file_groups: dict, max_files_per_type: int = 10):
    """Test a sample of files from each type"""
    logging.info(f"\n🧪 TESTING SAMPLE FILES (max {max_files_per_type} per type)")
    logging.info("=" * 50)
    
    results = defaultdict(list)
    
    for file_type, files in file_groups.items():
        logging.info(f"\nTesting {file_type} files...")
        
        # Test up to max_files_per_type files
        sample_files = files[:max_files_per_type]
        
        for i, filepath in enumerate(sample_files):
            file_info = {
                "type": file_type,
                "index": i + 1,
                "filename": os.path.basename(filepath),
                "size": os.path.getsize(filepath)
            }
            
            result = await test_stt_file(filepath, file_info)
            results[file_type].append(result)
            
            # Small delay between tests
            await asyncio.sleep(0.1)
    
    return results

def print_results(results: dict):
    """Print test results summary"""
    logging.info("\n📋 TEST RESULTS SUMMARY")
    logging.info("=" * 50)
    
    total_tests = 0
    total_processed = 0
    total_timeouts = 0
    total_errors = 0
    
    for file_type, type_results in results.items():
        processed = sum(1 for r in type_results if r["status"] == "processed")
        timeouts = sum(1 for r in type_results if r["status"] == "timeout")
        errors = sum(1 for r in type_results if r["status"] in ["error", "file_error"])
        
        total_tests += len(type_results)
        total_processed += processed
        total_timeouts += timeouts
        total_errors += errors
        
        logging.info(f"{file_type}:")
        logging.info(f"  Processed: {processed}/{len(type_results)}")
        logging.info(f"  Timeouts: {timeouts}")
        logging.info(f"  Errors: {errors}")
    
    logging.info(f"\nOVERALL:")
    logging.info(f"  Total tests: {total_tests}")
    logging.info(f"  Processed: {total_processed} ({total_processed/total_tests*100:.1f}%)")
    logging.info(f"  Timeouts: {total_timeouts} ({total_timeouts/total_tests*100:.1f}%)")
    logging.info(f"  Errors: {total_errors} ({total_errors/total_tests*100:.1f}%)")

async def main():
    logging.info("🎤 CAPTURED AUDIO STT TEST")
    logging.info("=" * 50)
    
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
    
    # Test sample files
    results = await test_sample_files(file_groups, max_files_per_type=5)
    
    # Print results
    print_results(results)
    
    logging.info("\n✅ Testing complete!")
    logging.info("Check local_ai_server logs for actual STT transcripts.")

if __name__ == "__main__":
    asyncio.run(main())
