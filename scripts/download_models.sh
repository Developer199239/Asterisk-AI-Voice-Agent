#!/bin/bash
set -e

MODELS_DIR="models"
STT_MODELS_DIR="$MODELS_DIR/stt"
LLM_MODELS_DIR="$MODELS_DIR/llm"
TTS_MODELS_DIR="$MODELS_DIR/tts"

VOSK_MODEL_URL="https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
VOSK_MODEL_DIR_NAME="vosk-model-small-en-us-0.15"
VOSK_MODEL_ZIP_NAME="vosk-model.zip"

LLAMA_MODEL_URL="https://huggingface.co/TheBloke/Llama-2-7B-Chat-GGUF/resolve/main/llama-2-7b-chat.Q4_K_M.gguf"
LLAMA_MODEL_NAME="llama-2-7b-chat.Q4_K_M.gguf"

PIPER_VOICE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
PIPER_VOICE_NAME="en_US-lessac-medium.onnx"
PIPER_VOICE_JSON_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
PIPER_VOICE_JSON_NAME="en_US-lessac-medium.onnx.json"


echo "Creating models directory..."
mkdir -p "$STT_MODELS_DIR"
mkdir -p "$LLM_MODELS_DIR"
mkdir -p "$TTS_MODELS_DIR"

if [ ! -d "$STT_MODELS_DIR/$VOSK_MODEL_DIR_NAME" ]; then
  echo "Downloading Vosk model..."
  curl -L "$VOSK_MODEL_URL" -o "$STT_MODELS_DIR/$VOSK_MODEL_ZIP_NAME"
  
  echo "Unzipping Vosk model..."
  unzip "$STT_MODELS_DIR/$VOSK_MODEL_ZIP_NAME" -d "$STT_MODELS_DIR"
  
  echo "Cleaning up..."
  rm "$STT_MODELS_DIR/$VOSK_MODEL_ZIP_NAME"
else
  echo "Vosk model already exists. Skipping download."
fi

if [ ! -f "$LLM_MODELS_DIR/$LLAMA_MODEL_NAME" ]; then
  echo "Downloading Llama model..."
  curl -L "$LLAMA_MODEL_URL" -o "$LLM_MODELS_DIR/$LLAMA_MODEL_NAME"
else
  echo "Llama model already exists. Skipping download."
fi

if [ ! -f "$TTS_MODELS_DIR/$PIPER_VOICE_NAME" ]; then
  echo "Downloading Piper voice model..."
  curl -L "$PIPER_VOICE_URL" -o "$TTS_MODELS_DIR/$PIPER_VOICE_NAME"
  curl -L "$PIPER_VOICE_JSON_URL" -o "$TTS_MODELS_DIR/$PIPER_VOICE_JSON_NAME"
else
  echo "Piper voice model already exists. Skipping download."
fi

echo "Model setup complete."
