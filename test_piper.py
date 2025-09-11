import os
from piper import PiperVoice
import wave

# This script is designed to be run inside the Docker container
# to test the Piper TTS engine in isolation.

# --- Configuration ---
# Absolute paths inside the container
MODEL_PATH = "/app/models/tts/en_US-lessac-medium.onnx"
OUTPUT_WAV_PATH = "/app/test_output.wav"
TEXT_TO_SYNTHESIZE = "Hello, this is a test of the Piper text to speech system."

def main():
    """
    Main function to load the model, synthesize audio, and save it to a file.
    """
    print("--- Starting Piper TTS Isolation Test ---")

    # 1. Verify Model Files Exist
    print(f"Checking for model file at: {MODEL_PATH}")
    if not os.path.exists(MODEL_PATH):
        print(f"ERROR: Model file not found at {MODEL_PATH}")
        return

    config_path = f"{MODEL_PATH}.json"
    print(f"Checking for config file at: {config_path}")
    if not os.path.exists(config_path):
        print(f"ERROR: Config file not found at {config_path}")
        return
    
    print("Model and config files found.")

    # 2. Load the Piper Voice Model
    try:
        print(f"Loading voice from: {MODEL_PATH}")
        voice = PiperVoice.load(MODEL_PATH)
        print("Successfully loaded PiperVoice model.")
    except Exception as e:
        print(f"ERROR: Failed to load PiperVoice model: {e}")
        return

    # 3. Synthesize Audio to a WAV file
    try:
        print(f"Synthesizing text: '{TEXT_TO_SYNTHESIZE}'")
        with wave.open(OUTPUT_WAV_PATH, "wb") as wav_file:
            # Set WAV parameters before synthesis
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(22050) # Piper default sample rate
            voice.synthesize(TEXT_TO_SYNTHESIZE, wav_file)
        
        print(f"Synthesis complete. Output saved to: {OUTPUT_WAV_PATH}")
    except Exception as e:
        print(f"ERROR: Failed during synthesis: {e}")
        return

    # 4. Verify the Output File
    if not os.path.exists(OUTPUT_WAV_PATH):
        print("ERROR: Output file was not created.")
        return

    file_size = os.path.getsize(OUTPUT_WAV_PATH)
    print(f"Output file size: {file_size} bytes")

    if file_size <= 44:
        print("TEST FAILED: The synthesized audio file is empty or contains only a WAV header.")
    else:
        print("TEST PASSED: The synthesized audio file appears to contain valid data.")
    
    print("--- Piper TTS Isolation Test Finished ---")

if __name__ == "__main__":
    main()
