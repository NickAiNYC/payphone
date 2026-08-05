import asyncio
import wave
import io
import os
import sys
import numpy as np

# Ensure root of hermes-agent is in Python path to import skills
sys.path.append(os.path.join(os.path.dirname(__file__), "skills"))

from voice_avatar.voice.pipeline import VoicePipeline, VoiceConfig
from voice_avatar.avatar.state_machine import AvatarStateMachine
from voice_avatar.consent.policy import RawMediaPolicy
from voice_avatar.consent.manager import ConsentManager
from voice_avatar.voice.llm.mock import MockLLM


async def main():
    print("=== Starting Cognitive Loop Integration Test ===")

    # 1. Generate a dummy audio file containing "Hello" using numpy
    # Whisper expects 16-bit 16kHz PCM (mono)
    sample_rate = 16000
    duration = 2.0
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    # Simple sine wave frequency (440Hz)
    audio_data = np.sin(2 * np.pi * 440 * t)
    audio_data_int16 = (audio_data * 32767).astype(np.int16)
    audio_bytes = audio_data_int16.tobytes()
    print("Generated 2 seconds of dummy 16kHz 16-bit PCM audio.")

    # 2. Setup the Pipeline Components
    config = VoiceConfig(
        stt={"provider": "faster-whisper", "model": "tiny"},
        tts={"provider": "piper", "model_path": "en_US-ryan-high.onnx"},
        vad={"provider": "silero", "threshold": 0.5},
    )

    llm = MockLLM()
    avatar = AvatarStateMachine()

    # Mock Consent Managers
    consent_mgr = ConsentManager(nostr_client=None)
    policy = RawMediaPolicy(consent_manager=consent_mgr)

    # Override fetch_grant to return opt-in so local-first validations pass
    async def mock_fetch_grant(hpk, apk):
        class MockGrant:
            server_processing_opt_in = True

        return MockGrant()

    policy.fetch_grant = mock_fetch_grant

    pipeline = VoicePipeline(
        config=config,
        llm_stream=llm,
        avatar=avatar,
        policy=policy,
        human_pubkey="human_pubkey",
        agent_pubkey="agent_pubkey",
    )

    # Track output validation variables
    received_emotions = []
    received_states = []
    synthesized_audio_size = 0

    # Attach listeners / hooks
    pipeline.on_emotion = lambda e, i: received_emotions.append((e, i))
    pipeline.on_state = lambda s: received_states.append(s)

    async def out_audio_callback(chunk):
        nonlocal synthesized_audio_size
        synthesized_audio_size += len(chunk)

    pipeline._out_audio = out_audio_callback

    # Start pipeline
    print("Starting voice pipeline...")
    await pipeline.start()

    # Stub the STT model to return "Hello" to guarantee cognitive loop execution
    async def mock_transcribe(audio):
        return "Hello"

    pipeline.stt.transcribe = mock_transcribe

    # 3. Execute process_utterance
    print("Feeding dummy audio into the pipeline...")
    await pipeline.process_utterance(audio_bytes)

    # 4. Verify Results
    print("\n=== Test Verification ===")
    print(f"Received Emotion Events: {received_emotions}")
    print(f"Received State Transitions: {received_states}")
    print(f"Synthesized Output Audio Size: {synthesized_audio_size} bytes")

    # Assertions
    assert len(received_emotions) > 0, "No emotion tags were parsed or received!"
    assert "happy" in [
        e[0] for e in received_emotions
    ], "Expected 'happy' emotion tag to be parsed!"
    assert synthesized_audio_size > 0, "No audio was synthesized by the TTS engine!"

    print("\nSUCCESS: The async cognitive loop executed and verified perfectly!")


if __name__ == "__main__":
    asyncio.run(main())
