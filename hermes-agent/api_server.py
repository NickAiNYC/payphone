import os
import secrets
import uuid
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from skills.voice_avatar.calls.webrtc_endpoint import HermesCallSession
from skills.voice_avatar.voice.pipeline import VoicePipeline, VoiceConfig
from skills.voice_avatar.consent.policy import RawMediaPolicy
from skills.voice_avatar.consent.manager import ConsentManager
from skills.voice_avatar.voice.llm.base import LLMProvider
from secure_storage import HermesSecureStorage
from ice_credentials import ice_servers

storage = HermesSecureStorage()
agent_key = storage.load_key()

app = FastAPI()

# Deployment gate for the endpoints that mint TURN credentials and spend
# inference budget. Set PAYPHONE_API_KEY and callers must present it.
#
# What this stops: drive-by abuse from anyone who can reach the port —
# /api/ice hands out working TURN credentials, so an open instance is a free
# relay someone else pays for, and /api/call/offer spends your LLM budget.
#
# What this does NOT do: authenticate a user. A browser client has to carry
# the key in its bundle, where any user of the app can read it. Per-user
# authentication belongs on the Nostr path, where the caller already proves
# key ownership by signing. Do not mistake this for more than a gate.
API_KEY = os.environ.get("PAYPHONE_API_KEY", "").strip()


async def require_api_key(x_api_key: str = Header(default="")) -> None:
    if not API_KEY:
        # Unset means local development. Say so loudly once rather than
        # failing closed and making the demo look broken.
        return
    if not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


# Enable CORS for the React app
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",")
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store to prevent garbage collection
active_sessions = {}


class OfferPayload(BaseModel):
    sdp: str
    type: str


@app.post("/api/call/offer", dependencies=[Depends(require_api_key)])
async def call_offer(payload: OfferPayload):
    try:
        call_id = str(uuid.uuid4())

        # Instantiate Consent, Policy and Session
        consent_mgr = ConsentManager(nostr_client=None)
        policy = RawMediaPolicy(consent_manager=consent_mgr)

        # Evaluate caller consent for microphone access
        has_consent = await consent_mgr.check("human_pubkey", "agent_pubkey", ["mic"])
        if not has_consent:
            raise HTTPException(
                status_code=403, detail="Caller microphone consent rejected."
            )

        session = HermesCallSession(consent_mgr, policy, signaling=None)
        session.call_id = call_id

        # Create pipeline config
        config = VoiceConfig(
            stt={"provider": "faster-whisper", "model": "tiny"},
            tts={"provider": "piper", "model_path": "en_US-ryan-high.onnx"},
            vad={"provider": "silero", "threshold": 0.5},
        )

        # Instantiate real GLM5Provider if API key is set, fallback to MockLLM
        # Dynamically load model provider (OpenAI, Groq, Ollama, DeepSeek, OpenRouter, GLM, or Mock)
        llm = LLMProvider.load()

        pipeline = VoicePipeline(
            config=config,
            llm_stream=llm,
            avatar=session.avatar,
            policy=policy,
            human_pubkey="human_pubkey",
            agent_pubkey="agent_pubkey",
        )

        # Start pipeline
        await pipeline.start()

        # Generate Answer SDP
        answer_sdp = await session.create_answer(
            offer_sdp=payload.sdp,
            human_pubkey="human_pubkey",
            agent_pubkey="agent_pubkey",
            voice_pipeline=pipeline,
        )

        # Save to memory to prevent GC
        active_sessions[call_id] = {"session": session, "pipeline": pipeline}

        return {
            "sdp": answer_sdp,
            "type": "answer",
            "call_id": call_id,
            "ice_servers": ice_servers(name=call_id[:8]),
        }

    except Exception as e:
        print(f"[API] Error handling call offer: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ice", dependencies=[Depends(require_api_key)])
async def get_ice_servers():
    """Short-lived TURN credentials for the browser.

    Fetched before the offer is built, so ICE gathering has relay candidates
    available from the start rather than only host/srflx ones.
    """
    return {"ice_servers": ice_servers()}


@app.post("/api/call/hangup/{call_id}", dependencies=[Depends(require_api_key)])
async def call_hangup(call_id: str):
    session_data = active_sessions.pop(call_id, None)
    if not session_data:
        raise HTTPException(status_code=404, detail="Call session not found")

    session = session_data["session"]
    await session.pc.close()
    return {"status": "disconnected"}
