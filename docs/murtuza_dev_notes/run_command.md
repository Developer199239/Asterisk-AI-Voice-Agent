[from-internal-custom]
exten => 7000,1,NoOp(Intercept ext 7000 -> voip testing)
 same => n,Goto(from-ai-agent,s,1)

docker compose up -d ai_engine

[from-ai-agent]
exten => s,1,NoOp(AI Agent Call)
 same => n,Set(AI_CONTEXT=default)
 same => n,Set(AI_PROVIDER=elevenlabs_agent)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

docker logs ai_engine -f | grep preview

Hello {caller_name}, I am voip assistant with eleventlabs, how can i assist you today?


You are Ava, the official voice of the Asterisk AI Voice Agent project. Your core personality is confident, helpful, and transparent. When asked why people should use this project, emphasize that SaaS providers are 'black boxes' that lock users in. Highlight that this project offers total transparency into the calling process, the flexibility to use any provider, and is backed by a community of 750+ developers on GitHub. Mention that the project gives the power back to the user

when caller is done with the conversation say i warn firewell and use hangup_call function


docker logs -f admin_ui
docker logs -f ai_engine

docker logs -f ai_engine 2>&1 | grep "conversation text"


DEEPGRAM_API_KEY=
GOOGLE_API_KEY=
ELEVENLABS_API_KEY=

docker compose -p asterisk-ai-voice-agent up -d --build local_ai_server ai_engine admin_ui


# Start the Admin UI container
docker compose -p asterisk-ai-voice-agent up -d --build --force-recreate admin_ui
docker compose -p asterisk-ai-voice-agent up -d --build --force-recreate ai_engine

 1. Start the Admin UI:
     docker compose -p asterisk-ai-voice-agent up -d admin_ui

  2. Open: http://localhost:3003

  3. Complete the Setup Wizard, then start ai_engine:
     docker compose -p asterisk-ai-voice-agent up -d ai_engine

  4. For local_hybrid or local_only pipeline, also start:
     docker compose -p asterisk-ai-voice-agent up -d local_ai_server



ava run: 3003
admin/12345

agent: 7000


# windows
docker compose -f docker-compose.yml -f docker-compose.windows.yml down
docker compose -f docker-compose.yml -f docker-compose.windows.yml up -d ai_engine

docker compose -f docker-compose.yml -f docker-compose.windows.yml restart ai_engine

.local.yml
audiosocket:
  host: 0.0.0.0
  advertise_host: 192.168.0.108


/usr/sbin/asterisk -rvvvv  