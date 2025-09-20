#!/usr/bin/env python3
"""
Analyze the actual audio content of captured files to understand
why STT is not detecting speech.
"""

import os
import glob
import struct
import logging
import statistics

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def analyze_audio_file(filepath: str):
    """Analyze a single audio file for content"""
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
        
        # Check for silence (all zeros or very low values)
        silence_threshold = 100  # Adjust based on testing
        is_silence = max_amplitude < silence_threshold
        
        # Check for consistent values (might indicate noise or corruption)
        unique_values = len(set(samples))
        is_constant = unique_values < 10
        
        return {
            "status": "analyzed",
            "size": len(audio_data),
            "samples": len(samples),
            "max_amplitude": max_amplitude,
            "avg_amplitude": avg_amplitude,
            "rms": rms,
            "is_silence": is_silence,
            "is_constant": is_constant,
            "unique_values": unique_values,
            "first_10_samples": samples[:10],
            "last_10_samples": samples[-10:]
        }
        
    except Exception as e:
        return {"status": "error", "error": str(e)}

def analyze_captured_audio(capture_dir: str, sample_size: int = 20):
    """Analyze captured audio files to understand content"""
    logging.info(f"Analyzing audio content in: {capture_dir}")
    
    raw_files = glob.glob(os.path.join(capture_dir, "*.raw"))
    logging.info(f"Found {len(raw_files)} .raw files")
    
    if not raw_files:
        logging.error("No audio files found!")
        return
    
    # Sample files for analysis
    sample_files = raw_files[:sample_size]
    logging.info(f"Analyzing {len(sample_files)} sample files")
    
    results = []
    silence_count = 0
    constant_count = 0
    error_count = 0
    
    for i, filepath in enumerate(sample_files):
        filename = os.path.basename(filepath)
        logging.info(f"Analyzing {i+1}/{len(sample_files)}: {filename}")
        
        result = analyze_audio_file(filepath)
        result["filename"] = filename
        results.append(result)
        
        if result["status"] == "error":
            error_count += 1
        elif result["status"] == "analyzed":
            if result["is_silence"]:
                silence_count += 1
            if result["is_constant"]:
                constant_count += 1
    
    # Print analysis summary
    logging.info("\n📊 AUDIO CONTENT ANALYSIS")
    logging.info("=" * 50)
    logging.info(f"Files analyzed: {len(sample_files)}")
    logging.info(f"Silence files: {silence_count} ({silence_count/len(sample_files)*100:.1f}%)")
    logging.info(f"Constant files: {constant_count} ({constant_count/len(sample_files)*100:.1f}%)")
    logging.info(f"Error files: {error_count} ({error_count/len(sample_files)*100:.1f}%)")
    
    # Show detailed results for non-silence files
    non_silence_files = [r for r in results if r["status"] == "analyzed" and not r["is_silence"]]
    if non_silence_files:
        logging.info(f"\n✅ Non-silence files found: {len(non_silence_files)}")
        for result in non_silence_files[:5]:  # Show first 5
            logging.info(f"  {result['filename']}: max={result['max_amplitude']}, avg={result['avg_amplitude']:.1f}, rms={result['rms']:.1f}")
    else:
        logging.warning("❌ No non-silence files found - all captured audio appears to be silence!")
    
    # Show sample data from first few files
    logging.info(f"\n🔍 SAMPLE AUDIO DATA")
    logging.info("=" * 50)
    for result in results[:3]:
        if result["status"] == "analyzed":
            logging.info(f"{result['filename']}:")
            logging.info(f"  First 10 samples: {result['first_10_samples']}")
            logging.info(f"  Last 10 samples: {result['last_10_samples']}")
            logging.info(f"  Max amplitude: {result['max_amplitude']}")
            logging.info(f"  Is silence: {result['is_silence']}")
            logging.info(f"  Is constant: {result['is_constant']}")

def main():
    logging.info("🎵 AUDIO CONTENT ANALYZER")
    logging.info("=" * 50)
    logging.info("Analyzing captured audio files to understand STT detection issues")
    
    # Find the latest capture directory
    capture_dirs = sorted(glob.glob("/app/audio_capture_*/"), reverse=True)
    if not capture_dirs:
        logging.error("No audio capture directories found!")
        return
    
    latest_capture_dir = capture_dirs[0]
    logging.info(f"Using latest capture directory: {latest_capture_dir}")
    
    # Analyze audio content
    analyze_captured_audio(latest_capture_dir, sample_size=30)

if __name__ == "__main__":
    main()
