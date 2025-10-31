import yaml

# Load existing config
with open("/root/Asterisk-AI-Voice-Agent/config/ai-agent.yaml") as f:
    config = yaml.safe_load(f)

# Add demo contexts
config["contexts"]["demo_deepgram"] = {
    "greeting": "Hi, I am AAVA for Deepgram. Ask me about the Asterisk AI Voice Agent project or how I work!",
    "prompt": "You are AAVA (Asterisk AI Voice Agent) demonstrating the Deepgram Voice Agent configuration. ABOUT THIS PROJECT: Asterisk AI Voice Agent integrates AI voice capabilities with Asterisk PBX. Supports multiple AI providers: Deepgram, OpenAI Realtime, and local AI. Uses ARI for call control. YOUR ROLE: Explain this demo and answer questions about the project architecture and features concisely.",
    "profile": "telephony_ulaw_8k",
    "provider": "deepgram"
}

config["contexts"]["demo_openai"] = {
    "greeting": "Hello, I'm AAVA powered by OpenAI Realtime. I can tell you about this voice AI project!",
    "prompt": "You are AAVA demonstrating OpenAI Realtime API integration. Real-time voice AI integration with Asterisk PBX. Multiple provider support. Production-ready architecture with ARI. Explain the project and answer questions concisely.",
    "profile": "openai_realtime_24k",
    "provider": "openai_realtime"
}

config["contexts"]["demo_hybrid"] = {
    "greeting": "Hey there! I'm AAVA running on a hybrid local pipeline. Want to know about the project?",
    "prompt": "You are AAVA demonstrating the local hybrid pipeline (Vosk STT + OpenAI LLM + Piper TTS). This shows how to mix cloud and local AI components. Explain the project capabilities briefly.",
    "profile": "telephony_ulaw_8k"
}

# Save back
with open("/root/Asterisk-AI-Voice-Agent/config/ai-agent.yaml", "w") as f:
    yaml.dump(config, f, default_flow_style=False)

print("✅ Added demo contexts to ai-agent.yaml")
print("\nContexts now in config:")
for name in sorted(config["contexts"].keys()):
    print(f"  - {name}")
