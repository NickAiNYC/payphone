import React, { useState, useRef, useEffect } from "react";
import { ConsentSheet } from "@buzz/ui/src/ConsentSheet";
import { ConsentGrant } from "@buzz/agent-consent/src/types";
import { AvatarStateMachine } from "@buzz/agent-avatars/src/AvatarStateMachine";
import { CanvasSpriteRenderer } from "@buzz/agent-avatars/src/renderers/CanvasSpriteRenderer";
import { NostrSignaling } from "@buzz/nostr/src/NostrSignaling";
import { HuddlePanel } from "@buzz/huddle/src/HuddlePanel";

const App: React.FC = () => {
  const [needsConsent, setNeedsConsent] = useState(false);
  const [callActive, setCallActive] = useState(false);
  const [huddleActive, setHuddleActive] = useState(false);
  const [grant, setGrant] = useState<ConsentGrant | null>(null);
  const [isUserSpeaking, setIsUserSpeaking] = useState(false);
  const avatarRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<CanvasSpriteRenderer | null>(null);
  const smRef = useRef<AvatarStateMachine | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const signalingRef = useRef<NostrSignaling | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const vadIntervalRef = useRef<any>(null);

  const huddleRoom = "test-huddle-room";
  const huddleToken = "mock-token-for-huddle-connection";
  const agentPubkey = "agent_pubkey_mock_value";

  useEffect(() => {
    if (avatarRef.current && !rendererRef.current) {
      const renderer = new CanvasSpriteRenderer();
      const sm = new AvatarStateMachine();
      renderer.mount(avatarRef.current);
      sm.on(e => renderer.applyState(e));
      rendererRef.current = renderer;
      smRef.current = sm;
      sm.wake();
      sm.transition({ s: "idle" });
    }
    return () => { 
      rendererRef.current?.unmount(); 
      cleanupAudio();
    };
  }, []);

  const handleCallClick = () => {
    if (!grant || grant.expiration <= Date.now()) {
      setNeedsConsent(true);
    } else {
      startCall();
    }
  };

  const handleHuddleClick = () => {
    setHuddleActive(true);
  };

  const handleApproveConsent = (g: ConsentGrant) => {
    setGrant(g);
    setNeedsConsent(false);
    startCall();
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
      const defaultRelay =
        typeof window !== "undefined" && window.location?.host
          ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/nostr`
          : "ws://localhost:8080";
      const relayUrl = (import.meta as any).env?.VITE_RELAY_URL || defaultRelay;
      signalingRef.current = new NostrSignaling(relayUrl, agentPubkey);
      pcRef.current = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
      
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
    smRef.current?.transition({ s: "idle" });
    cleanupAudio();
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }
    signalingRef.current = null;
  };

  return (
    <div style={{ padding: "2rem", background: "#111", color: "#eee", minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center" }}>
      <h1>Buzz × Hermes Test Environment</h1>
      <p>Local-first voice & avatar system is initialized.</p>
      
      {huddleActive ? (
        <HuddlePanel 
          roomName={huddleRoom} 
          token={huddleToken} 
          onDisconnect={() => setHuddleActive(false)} 
        />
      ) : (
        <>
          {/* Avatar Stage */}
          <div style={{ display: "flex", justifyContent: "center", alignItems: "center", margin: "2rem 0", border: "1px solid #333", borderRadius: "12px", padding: "1rem", background: "#000", position: "relative" }}>
            <div ref={avatarRef} style={{ width: "400px", height: "400px" }} />
            {callActive && (
              <div style={{ position: "absolute", bottom: "10px", right: "20px", background: isUserSpeaking ? "#34C759" : "#555", padding: "4px 8px", borderRadius: "4px", fontSize: "12px", fontWeight: "bold" }}>
                {isUserSpeaking ? "🎙️ USER SPEAKING" : "🔇 USER SILENT"}
              </div>
            )}
          </div>

          {/* Controls */}
          <div style={{ display: "flex", gap: "1rem" }}>
            <button 
              onClick={handleCallClick} 
              disabled={callActive}
              style={{ padding: "10px 20px", background: callActive ? "#555" : "#4A90E2", color: "white", border: "none", borderRadius: "4px", cursor: callActive ? "not-allowed" : "pointer", fontSize: "16px" }}
            >
              {callActive ? "🔴 Call Active" : "📞 Call Agent"}
            </button>
            
            <button 
              onClick={handleHuddleClick}
              disabled={callActive}
              style={{ padding: "10px 20px", background: "#34C759", color: "white", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "16px" }}
            >
              👥 Join Huddle Room
            </button>

            {callActive && (
              <button 
                onClick={hangup}
                style={{ padding: "10px 20px", background: "#E24A4A", color: "white", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "16px" }}
              >
                ❌ Hangup
              </button>
            )}
          </div>
        </>
      )}

      {/* Consent Modal */}
      {needsConsent && (
        <ConsentSheet 
          agentName="Hermes" 
          scopes={["mic", "tools_during_call"]} 
          onApprove={handleApproveConsent} 
        />
      )}
    </div>
  );
};

export default App;
