import asyncio
import json
import websockets
import os
import sys
import hashlib
import time

from coincurve import PrivateKey

from nip44 import (
    decrypt as nip44_decrypt,
    encrypt as nip44_encrypt,
    generate_privkey,
    get_conversation_key,
    pubkey_from_privkey,
)

# Ensure skills is in path
sys.path.append(os.path.join(os.path.dirname(__file__), "skills"))

from voice_avatar.calls.webrtc_endpoint import HermesCallSession
from voice_avatar.voice.pipeline import VoicePipeline, VoiceConfig
from voice_avatar.consent.policy import RawMediaPolicy
from voice_avatar.consent.manager import ConsentManager
from voice_avatar.voice.llm.base import LLMProvider
from secure_storage import HermesSecureStorage
from ice_credentials import ice_servers

RELAY_URL = os.environ.get("RELAY_URL", "ws://localhost:8080")
storage = HermesSecureStorage()
AGENT_PRIVKEY_HEX = storage.load_key()
# Derived from the stored key, not a placeholder string — ECDH needs a real
# public key, and callers address the agent by it.
AGENT_PUBKEY = pubkey_from_privkey(AGENT_PRIVKEY_HEX)

# In-memory active session store
active_sessions = {}


def decrypt_from(peer_pubkey: str, ciphertext: str) -> str:
    """Decrypt a NIP-44 payload sent to this agent by `peer_pubkey`.

    Raises on a bad MAC. There is deliberately no plaintext fallback: the
    previous implementation returned the ciphertext unchanged on failure, which
    silently accepted unencrypted input.
    """
    key = get_conversation_key(AGENT_PRIVKEY_HEX, peer_pubkey)
    return nip44_decrypt(ciphertext, key)


def encrypt_to(peer_pubkey: str, plaintext: str, privkey: str = None) -> str:
    key = get_conversation_key(privkey or AGENT_PRIVKEY_HEX, peer_pubkey)
    return nip44_encrypt(plaintext, key)


def finalize_event(privkey_hex: str, kind: int, tags: list, content: str) -> dict:
    """Compute the NIP-01 event id and sign it. An event with a placeholder
    signature is rejected by any relay that validates, which is all of them."""
    priv = PrivateKey(bytes.fromhex(privkey_hex))
    pubkey = priv.public_key_xonly.format().hex()
    created_at = int(time.time())
    canonical = json.dumps(
        [0, pubkey, created_at, kind, tags, content],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    event_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "id": event_id,
        "pubkey": pubkey,
        "created_at": created_at,
        "kind": kind,
        "tags": tags,
        "content": content,
        "sig": priv.sign_schnorr(bytes.fromhex(event_id)).hex(),
    }


async def publish_event(websocket, kind, target_pubkey, content):
    # 1. Create Rumor
    rumor = {
        "kind": kind,
        "pubkey": AGENT_PUBKEY,
        "created_at": int(time.time()),
        "tags": [["p", target_pubkey]],
        "content": json.dumps(content),
    }

    # 2. Seal: rumor encrypted to the recipient, signed by the agent so the
    #    recipient can prove who actually sent it.
    seal = finalize_event(
        AGENT_PRIVKEY_HEX,
        14,
        [],
        encrypt_to(target_pubkey, json.dumps(rumor)),
    )

    # 3. Gift wrap: seal encrypted and signed under a throwaway key, so the
    #    relay cannot correlate sender and recipient across events. The wrap
    #    carries the throwaway's real pubkey — the recipient derives the
    #    conversation key from it.
    wrap_priv = generate_privkey()
    gift_wrap = finalize_event(
        wrap_priv,
        13,
        [["p", target_pubkey]],
        encrypt_to(target_pubkey, json.dumps(seal), privkey=wrap_priv),
    )
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

    answer_payload = {
        "type": "answer",
        "sdp": answer_sdp,
        "ice_servers": ice_servers(name=user_pubkey[:8]),
    }
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

                        # Outer layer is encrypted from the wrap's
                        # throwaway key; inner from the real sender's.
                        seal = json.loads(
                            decrypt_from(gift_wrap["pubkey"], gift_wrap["content"])
                        )

                        rumor = json.loads(
                            decrypt_from(seal["pubkey"], seal["content"])
                        )

                        # Trust the signed seal's author over the unsigned
                        # rumor's self-declared pubkey.
                        user_pubkey = seal["pubkey"]
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
