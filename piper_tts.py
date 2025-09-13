import subprocess
import tempfile
import os
import wave
from piper import PiperVoice

class PiperTTS:
    def __init__(self, model_path: str):
        self.voice = PiperVoice.load(model_path)
        self.temp_dir = "/tmp/piper_tts"
        os.makedirs(self.temp_dir, exist_ok=True)
    
    def tts(self, text: str) -> bytes:
        """
        Convert text to speech using Piper TTS with direct ulaw output for Asterisk compatibility
        
        Args:
            text: Text to convert to speech
            
        Returns:
            bytes: ulaw audio data at 8000 Hz sample rate
        """
        try:
            # Create temporary files
            wav_temp = os.path.join(self.temp_dir, f"piper_temp_{os.getpid()}.wav")
            ulaw_temp = os.path.join(self.temp_dir, f"piper_temp_{os.getpid()}.ulaw")
            
            # Generate WAV using Piper TTS
            wav_file = wave.open(wav_temp, "wb")
            self.voice.synthesize_wav(text, wav_file)
            wav_file.close()
            
            # Convert WAV to ulaw using sox
            sox_cmd = [
                "sox",
                wav_temp,                # Input WAV file
                "-r", "8000",            # Sample rate: 8000 Hz
                "-c", "1",               # Mono channel
                "-e", "mu-law",          # mu-law encoding
                "-t", "raw",             # Raw format
                ulaw_temp                # Output as ulaw file
            ]
            
            result = subprocess.run(sox_cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                print(f"sox conversion failed: {result.stderr}")
                return b""
            
            # Read the generated ulaw file
            if os.path.exists(ulaw_temp):
                with open(ulaw_temp, "rb") as f:
                    audio_data = f.read()
                
                # Clean up temporary files
                try:
                    os.unlink(wav_temp)
                    os.unlink(ulaw_temp)
                except:
                    pass
                
                print(f"Generated Piper TTS audio as ulaw at 8000 Hz: {len(audio_data)} bytes")
                return audio_data
            else:
                print("Piper TTS pipeline did not generate output file")
                return b""
                
        except subprocess.TimeoutExpired:
            print("Piper TTS pipeline timed out")
            return b""
        except Exception as e:
            print(f"Piper TTS generation failed: {e}")
            return b""
