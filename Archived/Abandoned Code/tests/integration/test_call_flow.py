import pytest
import asyncio
import json

@pytest.mark.asyncio
async def test_full_call_flow(redis_client):
    """
    Test a simplified end-to-end call flow:
    1. call_controller publishes a new call event.
    2. stt_service "receives" audio and publishes a transcription.
    3. llm_service receives the transcription and publishes a response.
    4. tts_service receives the response and "generates" audio.
    """
    channel_id = "test-channel-123"
    
    # 1. Simulate new call from call_controller
    new_call_message = {
        "channel_id": channel_id,
        "caller_id": "12345"
    }
    await redis_client.publish("calls:new", json.dumps(new_call_message))

    # 2. Simulate transcription from stt_service
    async def simulate_stt():
        await asyncio.sleep(0.1) # allow time for propagation
        transcription_message = {
            "channel_id": channel_id,
            "text": "Hello, world",
            "is_final": True
        }
        await redis_client.publish("stt:transcription:complete", json.dumps(transcription_message))
    
    # 3. Listen for LLM response
    async def listen_for_llm_response():
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("llm:response:ready")
        
        async for message in pubsub.listen():
            if message['type'] == 'message':
                response_data = json.loads(message['data'])
                if response_data.get('channel_id') == channel_id:
                    return response_data
    
    # 4. Listen for TTS completion
    async def listen_for_tts_completion():
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("tts:synthesis:complete") # Assuming this is the channel
        
        async for message in pubsub.listen():
            if message['type'] == 'message':
                tts_data = json.loads(message['data'])
                if tts_data.get('channel_id') == channel_id:
                    return tts_data

    # Run simulation and listeners concurrently
    stt_task = asyncio.create_task(simulate_stt())
    llm_listener_task = asyncio.create_task(listen_for_llm_response())
    tts_listener_task = asyncio.create_task(listen_for_tts_completion())

    await stt_task
    llm_response = await asyncio.wait_for(llm_listener_task, timeout=2)
    tts_response = await asyncio.wait_for(tts_listener_task, timeout=2)

    # Assertions
    assert llm_response is not None
    assert "text" in llm_response
    assert len(llm_response["text"]) > 0

    assert tts_response is not None
    assert "audio_file_path" in tts_response
    assert tts_response["audio_file_path"].startswith("/shared/audio/")
