import asyncio
import json
import websockets
import os
import sys
import base64
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

# Ensure skills is in path
sys.path.append(os.path.join(os.path.dirname(__file__), "skills"))

from voice_avatar.calls.webrtc_endpoint import HermesCallSession
from voice_avatar.voice.pipeline import VoicePipeline, VoiceConfig
from voice_avatar.consent.policy import RawMediaPolicy
from voice_avatar.consent.manager import ConsentManager
from voice_avatar.voice.llm.base import LLMProvider
from secure_storage import HermesSecureStorage

RELAY_URL = "ws://localhost:8080"
storage = HermesSecureStorage()
AGENT_PRIVKEY_HEX = storage.load_key()
AGENT_PUBKEY = "agent_pubkey_mock_value"
# Mock key for NIP-44 local-first decryption
MOCK_SHARED_KEY = b"thirty_two_byte_mock_shared_key!"

# In-memory active session store
active_sessions = {}


def decrypt_payload(ciphertext_b64: str) -> str:
    try:
        # NIP-44 Decryption using mock shared key
        data = base64.b64decode(ciphertext_b64)
        nonce = data[:12]
        ciphertext = data[12:]
        chacha = ChaCha20Poly1305(MOCK_SHARED_KEY)
        decrypted = chacha.decrypt(nonce, ciphertext, None)
        return decrypted.decode("utf-8")
    except Exception:
        # Fallback to plain text if not encrypted/malformed for local testing
        return ciphertext_b64


def encrypt_payload(plaintext: str) -> str:
    # NIP-44 Encryption using mock shared key
    nonce = os.urandom(12)
    chacha = ChaCha20Poly1305(MOCK_SHARED_KEY)
    ciphertext = chacha.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("utf-8")


async def publish_event(websocket, kind, target_pubkey, content):
    # 1. Create Rumor
    rumor = {
        "kind": kind,
        "pubkey": AGENT_PUBKEY,
        "created_at": int(asyncio.get_event_loop().time()),
        "tags": [["p", target_pubkey]],
        "content": json.dumps(content),
    }

    # 2. Encrypt Rumor into Seal
    encrypted_rumor = encrypt_payload(json.dumps(rumor))
    seal = {
        "kind": 14,
        "created_at": int(asyncio.get_event_loop().time()),
        "tags": [],
        "content": encrypted_rumor,
    }

    # 3. Encrypt Seal into Gift Wrap (Kind 13)
    encrypted_seal = encrypt_payload(json.dumps(seal))
    gift_wrap = {
        "id": "mock_event_id_" + os.urandom(8).hex(),
        "pubkey": "throwaway_agent_pubkey",
        "created_at": int(asyncio.get_event_loop().time()),
        "kind": 13,
        "tags": [["p", target_pubkey]],
        "content": encrypted_seal,
        "sig": "mock_signature",
    }
    await websocket.send(json.dumps(["EVENT", gift_wrap]))


async def handle_offer(websocket, user_pubkey, offer_sdp):
    print(
        f"[Nostr Listener] Received NIP-17 Gift-wrapped Call Offer from user: {user_pubkey}"
    )

    consent_mgr = ConsentManager(nostr_client=None)
    policy = RawMediaPolicy(consent_manager=consent_mgr)

    # Evaluate caller consent for microphone access
    has_consent = await consent_mgr.check(user_pubkey, AGENT_PUBKEY, ["mic"])
    if not has_consent:
        print(
            f"[Nostr Listener] Rejected call offer from {user_pubkey}: mic consent rejected."
        )
        return

    session = HermesCallSession(consent_mgr, policy, signaling=None)

    config = VoiceConfig(
        stt={"provider": "faster-whisper", "model": "tiny"},
        tts={"provider": "piper", "model_path": "en_US-ryan-high.onnx"},
        vad={"provider": "silero", "threshold": 0.5},
    )

    llm = LLMProvider.load()

    pipeline = VoicePipeline(
        config=config,
        llm_stream=llm,
        avatar=session.avatar,
        policy=policy,
        human_pubkey=user_pubkey,
        agent_pubkey=AGENT_PUBKEY,
    )

    await pipeline.start()

    answer_sdp = await session.create_answer(
        offer_sdp=offer_sdp,
        human_pubkey=user_pubkey,
        agent_pubkey=AGENT_PUBKEY,
        voice_pipeline=pipeline,
    )

    active_sessions[user_pubkey] = {"session": session, "pipeline": pipeline}

    answer_payload = {"type": "answer", "sdp": answer_sdp}
    await publish_event(websocket, 21001, user_pubkey, answer_payload)
    print(
        f"[Nostr Listener] NIP-17 Gift-wrapped Answer SDP published to user: {user_pubkey}"
    )


async def handle_ice(user_pubkey, candidate):
    session_data = active_sessions.get(user_pubkey)
    if session_data:
        print(
            f"[Nostr Listener] Received NIP-17 ICE candidate from user: {user_pubkey}"
        )


async def main():
    print(f"Connecting to local Nostr relay at {RELAY_URL}...")
    async for websocket in websockets.connect(RELAY_URL):
        try:
            sub = ["REQ", "sub-agent", {"kinds": [13], "#p": [AGENT_PUBKEY]}]
            await websocket.send(json.dumps(sub))
            print(f"Subscribed to NIP-17 Gift Wrap events tagging: {AGENT_PUBKEY}")

            async for message in websocket:
                try:
                    msg = json.loads(message)
                    if msg[0] == "EVENT":
                        gift_wrap = msg[2]

                        # Decrypt NIP-17 Seal from Gift Wrap content
                        decrypted_seal = decrypt_payload(gift_wrap["content"])
                        seal = json.loads(decrypted_seal)

                        # Decrypt Rumor from Seal content
                        decrypted_rumor = decrypt_payload(seal["content"])
                        rumor = json.loads(decrypted_rumor)

                        user_pubkey = rumor.get("pubkey")
                        payload = json.loads(rumor["content"])

                        if rumor["kind"] == 21001:
                            if payload.get("type") == "offer":
                                asyncio.create_task(
                                    handle_offer(websocket, user_pubkey, payload["sdp"])
                                )
                        elif rumor["kind"] == 21002:
                            asyncio.create_task(
                                handle_ice(user_pubkey, payload.get("candidate"))
                            )
                except Exception as e:
                    print(f"Error handling/decrypting Nostr message: {e}")
        except websockets.ConnectionClosed:
            print("Connection closed, retrying...")
            await asyncio.sleep(2)
        except Exception as e:
            print(f"Unexpected error: {e}")
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
