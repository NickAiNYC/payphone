# payphone Developer Guide

This document covers system architecture mappings, setup procedures, extension guidelines, operations notes, and testing expectations for the payphone voice avatar ecosystem.

---

## 1. Directory Structure & Plane Mapping

The project maps directly to the three architecture planes:

```
payphone/
├── docker-compose.yml           # Multi-service local & cloud orchestrator
├── Makefile                     # Hot-keys for bootstrapping and testing
├── buzz/                        # Media Renderer & Client Control App (React)
│   ├── src/
│   │   ├── App.tsx              # Main UI, VAD Engine, WebRTC hooks
│   │   ├── main.tsx             # React SPA entrypoint
│   │   └── nostr_signaling.ts   # Client-side Nostr NIP-17 signaling module
│   └── packages/                # Shared internal React modules
│       ├── agent-avatars/       # CanvasSpriteRenderer & AvatarStateMachine
│       ├── agent-consent/       # Cryptographic Consent components
│       └── huddle/              # LiveKit Huddle UI panel
└── hermes-agent/                # Cognitive Agent Backend (Python)
    ├── api_server.py            # Local FastAPI fallback server
    ├── nostr_listener.py        # Nostr Daemon matching NostrSignaling
    └── skills/
        └── voice_avatar/        # Voice & Avatar skill package
            ├── skill.py         # Entrypoint mapping invite/join actions
            ├── avatar/          # State machine representations
            ├── consent/         # Authorization checks and policies
            ├── memory/          # Trace logs and GLM summarizing engine
            ├── self_improvement/# Interaction tuning analyzer (SkillRefiner)
            └── voice/           # Voice pipeline engine
                ├── pipeline.py  # Orchestrates STT -> LLM -> TTS stream
                ├── vad.py       # Local Silero voice activity detection wrapper
                ├── barge_in.py  # Interruption coordinator
                ├── llm/         # Dynamic streaming LLM providers
                ├── stt/         # STT provider adapters (Whisper, etc.)
                └── tts/         # TTS provider adapters (Piper, etc.)
```

### Plane Alignment:
1. **Control Plane (Signaling & Identity)**: Managed on the frontend by `nostr_signaling.ts` and on the backend by `nostr_listener.py` alongside the `consent` check modules.
2. **Media Plane (Audio Streams & State Sync)**: Implemented via browser WebRTC APIs, `aiortc` (in `webrtc_endpoint.py`), the Canvas sprite renderer, and LiveKit.
3. **Cognitive Plane (Core Brain & Loop)**: Implemented in `VoicePipeline` orchestrating Whisper STT, LLM streaming, and Piper TTS, with self-improving proposing cycles inside the `self_improvement` directory.

---

## 2. Adding a New STT/TTS/VAD/LLM Provider

To extend capabilities on the Cognitive Plane, subclass the corresponding provider base classes.

### Example: Adding a custom TTS Provider
1. Open [skills/voice_avatar/voice/tts/base.py](hermes-agent/skills/voice_avatar/voice/tts/base.py).
2. Subclass `TTSProvider`:
   ```python
   # skills/voice_avatar/voice/tts/custom_tts.py
   from .base import TTSProvider, TTSEvent

   class CustomTTS(TTSProvider):
       def __init__(self, config: dict):
           self.voice_id = config.get("voice", "default_voice")

       async def synthesize(self, text: str):
           # Yield custom TTSEvent(kind="audio", payload=pcm_bytes)
           # Yield TTSEvent(kind="viseme", payload={"viseme": "O", "duration_ms": 100})
           pass

       async def cancel(self):
           # Interrupt current synthesis stream immediately
           pass
   ```
3. Register the provider in `TTSProvider.load()` inside [skills/voice_avatar/voice/tts/base.py](hermes-agent/skills/voice_avatar/voice/tts/base.py#L10-L15):
   ```python
   if config["provider"] == "custom":
       from .custom_tts import CustomTTS
       return CustomTTS(config)
   ```

---

## 3. Extending the AvatarStateMachine & Sprite Renderer

The system maps state changes through explicit transitions.

### 1. Backend Transition Model
Update `AvatarState` and `TRANSITIONS` in [skills/voice_avatar/avatar/state_machine.py](hermes-agent/skills/voice_avatar/avatar/state_machine.py#L4-L11).

### 2. Frontend State Handler
Open `buzz/packages/agent-avatars/src/AvatarStateMachine.ts` and mirror the state additions.
Update the sprite render loop in `CanvasSpriteRenderer.ts` to map state names to visual transitions, loading corresponding sprite indices or canvas coordinates.

---

## 4. Extending Nostr Event Kinds

When defining custom behaviors, follow the architecture's existing kinds:
* `21001`: Call Signaling - Offer / Answer SDP.
* `21002`: Ephemeral ICE Candidates.
* `21003`: Call Interaction Summary transmission.
* `21004`: Call Termination (Hangup).
* `21005`: Cryptographic Consent request / grant.

To add a new event kind:
1. Document the rumor payload structure in `DEVELOPING.md`.
2. Add support to [nostr_signaling.ts](buzz/src/nostr_signaling.ts) and wrap in NIP-17 Gift-wraps.
3. Parse the message kind inside [nostr_listener.py](hermes-agent/nostr_listener.py).

---

## 5. Security & Operations Notes

### Key Custody & Storage
* **Agent Private Keys**: Stored encrypted in the agent's filesystem via `HermesSecureStorage`. Do not commit keys to docker images or volume directories.
* **User Private Keys**: Stored in the browser's IndexedDB using cryptographically isolated origins. Never persist private keys in `localStorage` due to XSS vulnerability risks.

### Network Configuration for Self-Hosting (LiveKit + TURN)
To ensure calls route correctly through firewalls, configure host ports as follows:
* **TCP Port 8080**: Nostr strfry control relay.
* **TCP Port 7880**: LiveKit HTTP/Websocket signaling.
* **UDP Ports 50000-60000**: LiveKit WebRTC media streams.
* **TCP/UDP Port 3478**: coturn TURN/STUN server signaling.
* **UDP Ports 49152-65535**: coturn WebRTC media relay.

Ensure host server firewalls allow TCP/UDP ingress on these ports.

### Privacy Safeguards
* By default, audio tracks are transcribed locally on the host via `faster-whisper`.
* Cloud processing requires checking consent values (`server_processing_opt_in = true`) through the `RawMediaPolicy` manager before initializing external adapters.

---

## 6. Self-Improvement Loop & Testing Skill Diffs

After every call, the `VoiceSelfImprover` analyzes the `InteractionTrace` (capturing barge-ins, response latency, and emotional metrics) and generates a JSON patch proposal (RFC 6902) to adjust the voice profile settings.

### Testing Proposals:
* You can manually run the self-improver proposal test by running:
  ```bash
  docker compose run --rm hermes-agent python3 test_cognitive_loop.py
  ```
* Propose improvements locally and verify that they are correctly written to the memory store database without altering production profiles without user confirmation.

---

## 7. PR Checklist & Code Style
Before submitting a Pull Request, ensure:
1. `flake8` and `black` static checks pass on `hermes-agent/`.
2. Frontend builds cleanly via `npm run build` inside `buzz/`.
3. Integration test suite passes via `make test`.

---

## 8. Continuous Integration & Testing

We run all automated checks inside GitHub Actions:
* **Linter and Static Checks**: Python linting (`flake8` / `black`) and TypeScript compilation are checked.
* **Testing Pipeline**: Runs the complete unit and integration test suite via `pytest`.
* **Container Compilation**: Assures that the `Dockerfile` profiles build correctly.

### Running Verification Locally
* **Run Unit + Integration Tests**:
  ```bash
  make test
  ```
* **Validate Latency Budgets (Performance Tests)**:
  Asserts that voice propagation, barge-in detection, and room setup budgets are met:
  ```bash
  make test-perf
  ```
  The test cases are located in [tests/test_performance.py](hermes-agent/tests/test_performance.py). Ensure Docker Compose is fully running or build assets before execution.
