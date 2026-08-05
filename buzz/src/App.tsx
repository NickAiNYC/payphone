import React, { useState, useRef, useEffect, useCallback } from "react";
import { ConsentSheet } from "@buzz/ui/src/ConsentSheet";
import { ConsentGrant } from "@buzz/agent-consent/src/types";
import { AvatarStateMachine, AvatarState } from "@buzz/agent-avatars/src/AvatarStateMachine";
import { WebGLAvatarRenderer } from "@buzz/agent-avatars/src/renderers/WebGLAvatarRenderer";
import { CanvasSpriteRenderer } from "@buzz/agent-avatars/src/renderers/CanvasSpriteRenderer";
import { NostrSignaling } from "@buzz/nostr/src/NostrSignaling";
import { fetchProfile, profileLabel, tintFromImage, NostrProfile } from "@buzz/nostr/src/profile";
import { HuddlePanel } from "@buzz/huddle/src/HuddlePanel";
import "./styles.css";

/** Both renderers satisfy this; WebGL is preferred, canvas is the fallback. */
type AvatarRenderer = {
  mount(el: HTMLElement): void | Promise<void>;
  unmount(): void;
  applyState(e: any): void;
  applyViseme(v: string, ms: number): void;
  applyEmotion(e: string, i: number): void;
  setLevel?(v: number): void;
};

const STATE_COPY: Record<AvatarState, string> = {
  sleeping: "Asleep",
  idle: "Ready",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
  reacting: "Reacting",
  tool_using: "Running tools",
};

const EMOTION_GLOW: Record<string, string> = {
  neutral: "rgba(106,169,255,0.55)",
  happy: "rgba(90,240,180,0.55)",
  sad: "rgba(140,128,255,0.55)",
  curious: "rgba(255,190,92,0.55)",
  focused: "rgba(255,140,108,0.55)",
};

const Icon = {
  mic: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <rect x="9" y="2.5" width="6" height="11" rx="3" />
      <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" />
    </svg>
  ),
  micOff: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <path d="M15 5a3 3 0 0 0-6 0v5M9 13.2A3 3 0 0 0 15 12v-1" />
      <path d="M5.5 11a6.5 6.5 0 0 0 10.4 5.2M12 17.5V21M3.5 3l17 17" />
    </svg>
  ),
  people: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <circle cx="9" cy="8" r="3.2" />
      <path d="M2.8 19.5a6.2 6.2 0 0 1 12.4 0" />
      <path d="M16.2 5.2a3.2 3.2 0 0 1 0 5.9M17.4 14.2a6.2 6.2 0 0 1 3.8 5.3" />
    </svg>
  ),
  phone: (
    <svg viewBox="0 0 24 24" fill="currentColor">
      <path d="M6.6 2.7a1.7 1.7 0 0 1 2.3.6l1.5 2.6a1.7 1.7 0 0 1-.3 2.1L8.8 9.2a10.6 10.6 0 0 0 6 6l1.2-1.3a1.7 1.7 0 0 1 2.1-.3l2.6 1.5a1.7 1.7 0 0 1 .6 2.3l-1 1.7a2.6 2.6 0 0 1-2.9 1.2C11.6 18.8 5.2 12.4 3.7 5.6A2.6 2.6 0 0 1 4.9 2.7z" />
    </svg>
  ),
  hangup: (
    <svg viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 8.5c-2.6 0-5 .5-7 1.4v3a1.5 1.5 0 0 0 2.3 1.3l1.6-1a1.4 1.4 0 0 0 .7-1.2v-1.3c1.6-.4 3.2-.4 4.8 0V12a1.4 1.4 0 0 0 .7 1.2l1.6 1A1.5 1.5 0 0 0 19 12.9v-3c-2-.9-4.4-1.4-7-1.4z" transform="rotate(133 12 12)" />
    </svg>
  ),
};

/** Launched standalone from the Home Screen, or running on a phone-sized screen.
 *  In either case the drawn device bezel is redundant — the real device is the frame. */
function useNativeShell(): boolean {
  const [native, setNative] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(display-mode: standalone), (display-mode: fullscreen)");
    const evaluate = () =>
      setNative(
        mq.matches ||
          (window.navigator as any).standalone === true ||
          window.matchMedia("(max-width: 520px)").matches
      );
    evaluate();
    mq.addEventListener?.("change", evaluate);
    window.addEventListener("resize", evaluate);
    return () => {
      mq.removeEventListener?.("change", evaluate);
      window.removeEventListener("resize", evaluate);
    };
  }, []);
  return native;
}

/** Relay endpoint: same-origin /nostr proxy in production, overridable for dev. */
function relayUrl(): string {
  const derived =
    typeof window !== "undefined" && window.location?.host
      ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/nostr`
      : "ws://localhost:8080";
  return (import.meta as any).env?.VITE_RELAY_URL || derived;
}

const App: React.FC = () => {
  const [needsConsent, setNeedsConsent] = useState(false);
  const [callActive, setCallActive] = useState(false);
  const [huddleActive, setHuddleActive] = useState(false);
  const [grant, setGrant] = useState<ConsentGrant | null>(null);
  const [isUserSpeaking, setIsUserSpeaking] = useState(false);
  const [avatarState, setAvatarState] = useState<AvatarState>("idle");
  const [emotion, setEmotion] = useState("neutral");
  const [micLevel, setMicLevel] = useState(0);
  const [seconds, setSeconds] = useState(0);
  const [clock, setClock] = useState("");
  const [profile, setProfile] = useState<NostrProfile | null>(null);
  const nativeShell = useNativeShell();

  const avatarRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<AvatarRenderer | null>(null);
  const smRef = useRef<AvatarStateMachine | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const signalingRef = useRef<NostrSignaling | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const vadIntervalRef = useRef<any>(null);

  const huddleRoom = "test-huddle-room";
  const huddleToken = "mock-token-for-huddle-connection";
  const agentPubkey =
    (import.meta as any).env?.VITE_AGENT_PUBKEY || "agent_pubkey_mock_value";
  // Shown until the agent's kind 0 metadata arrives (or if it publishes none).
  const agentFallbackName = (import.meta as any).env?.VITE_AGENT_NAME || "Hermes";
  const agentName = profileLabel(profile, agentPubkey, agentFallbackName);

  useEffect(() => {
    if (avatarRef.current && !rendererRef.current) {
      const el = avatarRef.current;
      let renderer: AvatarRenderer = new WebGLAvatarRenderer();
      const sm = new AvatarStateMachine();
      renderer.mount(el);
      // Fall back to the 2D sprite renderer where WebGL2 is unavailable.
      if (renderer instanceof WebGLAvatarRenderer && !renderer.supported) {
        renderer.unmount();
        renderer = new CanvasSpriteRenderer();
        renderer.mount(el);
      }
      sm.on(e => {
        renderer.applyState(e);
        setAvatarState(e.s);
        setEmotion(e.e);
      });
      rendererRef.current = renderer;
      smRef.current = sm;
      sm.wake();
      sm.transition({ s: "idle" });

      // Dev-only handle for driving the avatar without a live call.
      if ((import.meta as any).env?.DEV) {
        (window as any).__payphone = { renderer, sm };
      }
    }
    return () => {
      rendererRef.current?.unmount();
      // Null the refs so React 18 StrictMode's second effect pass rebuilds the
      // renderer rather than holding on to the one it just tore down.
      rendererRef.current = null;
      smRef.current = null;
      cleanupAudio();
    };
  }, []);

  // Agent identity from its kind 0 metadata, and a tint sampled from its picture.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const p = await fetchProfile(relayUrl(), agentPubkey);
      if (cancelled || !p) return;
      setProfile(p);
      if (p.picture) {
        const tint = await tintFromImage(p.picture);
        if (!cancelled && tint) {
          (rendererRef.current as WebGLAvatarRenderer | null)?.setIdentityTint?.(tint);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [agentPubkey]);

  // status-bar clock
  useEffect(() => {
    const tick = () =>
      setClock(new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }));
    tick();
    const id = setInterval(tick, 10_000);
    return () => clearInterval(id);
  }, []);

  // call duration
  useEffect(() => {
    if (!callActive) { setSeconds(0); return; }
    const id = setInterval(() => setSeconds(s => s + 1), 1000);
    return () => clearInterval(id);
  }, [callActive]);

  const handleCallClick = () => {
    if (!grant || grant.expiration <= Date.now()) {
      setNeedsConsent(true);
    } else {
      startCall();
    }
  };

  const handleHuddleClick = () => setHuddleActive(true);

  const handleApproveConsent = (g: ConsentGrant) => {
    setGrant(g);
    setNeedsConsent(false);
    startCall();
  };

  /** Ask the agent for ICE servers; fall back to public STUN if it is unreachable. */
  const fetchIceServers = async (): Promise<RTCIceServer[]> => {
    const fallback: RTCIceServer[] = [{ urls: "stun:stun.l.google.com:19302" }];
    try {
      const res = await fetch("/api/ice", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const servers: RTCIceServer[] = data?.ice_servers ?? [];
      if (!servers.length) return fallback;
      const hasTurn = servers.some(s =>
        (Array.isArray(s.urls) ? s.urls : [s.urls]).some(u => String(u).startsWith("turn"))
      );
      if (!hasTurn) {
        console.warn("[ICE] No TURN server configured — calls over cellular/CGNAT will fail. Set TURN_HOST.");
      }
      return servers;
    } catch (err) {
      console.warn("[ICE] Could not reach /api/ice, using public STUN only:", err);
      return fallback;
    }
  };

  const setupClientVAD = (stream: MediaStream, audioTrack: MediaStreamTrack) => {
    audioContextRef.current = new AudioContext();
    const source = audioContextRef.current.createMediaStreamSource(stream);
    const analyser = audioContextRef.current.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);

    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    let silenceThreshold = 15; // Noise gate threshold
    let silenceTimeout = 800; // Keep track active for 800ms of silence (debounce)
    let lastSpokenTime = 0;

    vadIntervalRef.current = setInterval(() => {
      analyser.getByteFrequencyData(dataArray);
      let sum = 0;
      for (let i = 0; i < bufferLength; i++) {
        sum += dataArray[i];
      }
      const averageVolume = sum / bufferLength;

      // Feed the normalised level to the 3D renderer and the UI rings
      const norm = Math.min(1, averageVolume / 55);
      rendererRef.current?.setLevel?.(norm);
      setMicLevel(norm);

      if (averageVolume > silenceThreshold) {
        lastSpokenTime = Date.now();
        if (!audioTrack.enabled) {
          audioTrack.enabled = true;
          setIsUserSpeaking(true);
          console.log("[VAD] Voice activity detected. Resuming WebRTC audio stream.");
        }
      } else {
        if (Date.now() - lastSpokenTime > silenceTimeout) {
          if (audioTrack.enabled) {
            audioTrack.enabled = false;
            setIsUserSpeaking(false);
            console.log("[VAD] Silence detected. Pausing WebRTC audio stream (muted).");
          }
        }
      }
    }, 50);
  };

  const cleanupAudio = () => {
    if (vadIntervalRef.current) {
      clearInterval(vadIntervalRef.current);
      vadIntervalRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
  };

  const startCall = async () => {
    setCallActive(true);
    smRef.current?.transition({ s: "listening" });

    try {
      signalingRef.current = new NostrSignaling(relayUrl(), agentPubkey);
      // TURN credentials are short-lived and minted by the agent, so the secret
      // never reaches the browser. Without relay candidates a call from cellular
      // (behind carrier-grade NAT) cannot connect at all — STUN alone is not enough.
      const iceServers = await fetchIceServers();
      pcRef.current = new RTCPeerConnection({ iceServers });

      // Enforce Echo Cancellation, Noise Suppression, and AGC constraints
      const localStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        },
        video: false
      });

      const audioTrack = localStream.getAudioTracks()[0];
      localStream.getTracks().forEach(track => pcRef.current!.addTrack(track, localStream));

      // Setup client side VAD
      setupClientVAD(localStream, audioTrack);

      pcRef.current.ontrack = (event) => {
        const audio = new Audio();
        audio.srcObject = event.streams[0];
        audio.play().catch(e => console.error("Error playing audio track:", e));
      };

      pcRef.current.ondatachannel = (event) => {
        const channel = event.channel;
        if (channel.label === "avatar-state") {
          channel.onmessage = (e) => {
            try {
              const data = JSON.parse(e.data);
              if (data.type === "viseme") {
                rendererRef.current?.applyViseme(data.viseme, data.duration_ms);
              } else if (data.type === "emotion") {
                rendererRef.current?.applyEmotion(data.emotion, data.intensity);
                setEmotion(data.emotion);
              } else {
                smRef.current?.transition({
                  s: data.s,
                  e: data.e,
                  i: data.i
                });
              }
            } catch (err) {
              console.error("Error parsing avatar state message:", err);
            }
          };
        }
      };

      pcRef.current.onicecandidate = (event) => {
        if (event.candidate && signalingRef.current) {
          signalingRef.current.sendIce(event.candidate);
        }
      };

      signalingRef.current.onAnswer(async (sdp) => {
        if (pcRef.current) {
          await pcRef.current.setRemoteDescription(new RTCSessionDescription({
            type: "answer",
            sdp: sdp
          }));
          console.log("[Nostr Signaling] Call connected successfully!");
        }
      });

      signalingRef.current.onIce(async (candidateInit) => {
        if (pcRef.current) {
          await pcRef.current.addIceCandidate(new RTCIceCandidate(candidateInit));
        }
      });

      const offer = await pcRef.current.createOffer();
      await pcRef.current.setLocalDescription(offer);
      await signalingRef.current.sendOffer(offer.sdp!);

    } catch (err) {
      console.error("Failed to establish WebRTC connection:", err);
      hangup();
    }
  };

  const hangup = () => {
    setCallActive(false);
    setIsUserSpeaking(false);
    setMicLevel(0);
    smRef.current?.transition({ s: "idle" });
    cleanupAudio();
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }
    signalingRef.current = null;
  };

  const glow = EMOTION_GLOW[emotion] || EMOTION_GLOW.neutral;
  const mmss = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;

  return (
    <div className={`room${nativeShell ? " native" : ""}`}>
      <div className="aurora a" style={{ background: glow }} />
      <div
        className="aurora b"
        style={{ background: callActive ? "rgba(60,120,255,0.45)" : "rgba(120,90,255,0.32)" }}
      />
      <div className="grain" />

      <div className="phone">
        <div className="screen">
          {/* Dynamic Island */}
          <div className={`island${callActive ? " expanded" : ""}`}>
            <span className={`island-dot${callActive ? " live" : ""}`} />
            <span className="island-label">
              {callActive ? STATE_COPY[avatarState] : "payphone"}
            </span>
            {callActive && avatarState === "speaking" && (
              <span className="eq"><i /><i /><i /><i /></span>
            )}
            <span className="island-time">{callActive ? mmss : clock}</span>
          </div>

          {huddleActive ? (
            <div className="huddle-wrap">
              <HuddlePanel
                roomName={huddleRoom}
                token={huddleToken}
                onDisconnect={() => setHuddleActive(false)}
              />
            </div>
          ) : (
            <>
              <div className="stage">
                <div
                  className="avatar-halo"
                  style={{
                    background: glow,
                    opacity: 0.35 + micLevel * 0.4 + (avatarState === "speaking" ? 0.25 : 0),
                    transform: `scale(${1 + micLevel * 0.09})`,
                  }}
                />

                <div className="rings">
                  {[0.52, 0.68, 0.86].map((s, i) => (
                    <div
                      key={i}
                      className="ring"
                      style={{
                        width: `${s * 100}%`,
                        aspectRatio: "1",
                        transform: `scale(${1 + micLevel * (0.05 + i * 0.035)})`,
                        opacity: callActive ? 0.85 - i * 0.22 : 0.3 - i * 0.08,
                        borderColor: isUserSpeaking
                          ? "rgba(50,215,75,0.42)"
                          : "rgba(255,255,255,0.10)",
                      }}
                    />
                  ))}
                </div>

                <div ref={avatarRef} className="avatar-mount" />

                <div className="identity">
                  {profile?.picture && (
                    <img
                      className="agent-photo"
                      src={profile.picture}
                      alt=""
                      referrerPolicy="no-referrer"
                      onError={e => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                    />
                  )}
                  <h2>{agentName}</h2>
                  <p>
                    {callActive
                      ? `${STATE_COPY[avatarState]} · ${mmss}`
                      : profile?.about?.trim() || "Agent · local-first"}
                  </p>
                  <div className="pubkey">
                    {profile?.nip05 ? (
                      <>
                        <b>✓</b> {profile.nip05}
                      </>
                    ) : (
                      <>
                        <b>●</b> {agentPubkey.slice(0, 8)}…{agentPubkey.slice(-4)}
                      </>
                    )}
                  </div>
                </div>
              </div>

              {/* Controls */}
              <div className="dock">
                <div className="tray">
                  <button
                    className={`key${isUserSpeaking ? " on" : ""}`}
                    disabled={!callActive}
                    title={isUserSpeaking ? "Transmitting" : "Gated by VAD"}
                  >
                    {isUserSpeaking ? Icon.mic : Icon.micOff}
                    {isUserSpeaking ? "Live" : "Gated"}
                  </button>

                  <button className="key" onClick={handleHuddleClick} disabled={callActive}>
                    {Icon.people}
                    Huddle
                  </button>

                  <button
                    className={`key${callActive ? " danger" : ""}`}
                    onClick={callActive ? hangup : handleCallClick}
                  >
                    {callActive ? Icon.hangup : Icon.phone}
                    {callActive ? "End" : "Call"}
                  </button>

                  {!callActive && (
                    <div className="call-row">
                      <button className="key primary" onClick={handleCallClick}>
                        {Icon.phone}
                        Call {agentName.split(" ")[0]}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}

          {needsConsent && (
            <ConsentSheet
              agentName={agentName}
              scopes={["mic", "tools_during_call"]}
              onApprove={handleApproveConsent}
              onDeny={() => setNeedsConsent(false)}
            />
          )}

          <div className="home-indicator" />
        </div>
      </div>
    </div>
  );
};

export default App;
