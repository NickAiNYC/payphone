import React, { useEffect, useState, useRef } from "react";
import { Room, RoomEvent, Participant } from "livekit-client";
import { AvatarStateMachine } from "@buzz/agent-avatars/src/AvatarStateMachine";
import { CanvasSpriteRenderer } from "@buzz/agent-avatars/src/renderers/CanvasSpriteRenderer";

interface HuddlePanelProps {
  roomName: string;
  token: string;
  onDisconnect: () => void;
}

export const HuddlePanel: React.FC<HuddlePanelProps> = ({ roomName, token, onDisconnect }) => {
  const [room, setRoom] = useState<Room | null>(null);
  const [participants, setParticipants] = useState<Participant[]>([]);
  const avatarRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const renderers = useRef<Record<string, CanvasSpriteRenderer>>({});
  const stateMachines = useRef<Record<string, AvatarStateMachine>>({});

  useEffect(() => {
    const activeRoom = new Room();

    activeRoom
      .on(RoomEvent.ParticipantConnected, () => {
        setParticipants(Array.from(activeRoom.remoteParticipants.values()));
      })
      .on(RoomEvent.ParticipantDisconnected, (participant) => {
        setParticipants(Array.from(activeRoom.remoteParticipants.values()));
        // Clean up renderers
        renderers.current[participant.identity]?.unmount();
        delete renderers.current[participant.identity];
        delete stateMachines.current[participant.identity];
      })
      .on(RoomEvent.DataReceived, (payload, participant) => {
        if (!participant) return;
        try {
          const text = new TextDecoder().decode(payload);
          const stateEvent = JSON.parse(text);
          
          let sm = stateMachines.current[participant.identity];
          if (!sm) {
            sm = new AvatarStateMachine();
            stateMachines.current[participant.identity] = sm;
          }
          sm.transition({
            s: stateEvent.s,
            e: stateEvent.e,
            i: stateEvent.i
          });
        } catch (err) {
          console.error("Failed to parse LiveKit Data Channel Message:", err);
        }
      });

    const connectToRoom = async () => {
      try {
        console.log(`[Huddle] Connecting to LiveKit room: ${roomName}`);
        await activeRoom.connect("ws://localhost:7880", token);
        setRoom(activeRoom);
        setParticipants(Array.from(activeRoom.remoteParticipants.values()));
        
        // Publish microphone track
        await activeRoom.localParticipant.setMicrophoneEnabled(true);
      } catch (err) {
        console.error("Failed to connect to LiveKit Room:", err);
        onDisconnect();
      }
    };

    connectToRoom();

    return () => {
      activeRoom.disconnect();
      Object.values(renderers.current).forEach(r => r.unmount());
    };
  }, [roomName, token]);

  // Mount/Update Renderers for Remote Participants
  useEffect(() => {
    participants.forEach((p) => {
      const container = avatarRefs.current[p.identity];
      if (container && !renderers.current[p.identity]) {
        const renderer = new CanvasSpriteRenderer();
        const sm = new AvatarStateMachine();
        renderer.mount(container);
        sm.on((e) => renderer.applyState(e));
        
        renderers.current[p.identity] = renderer;
        stateMachines.current[p.identity] = sm;
        sm.wake();
        sm.transition({ s: "idle" });
      }
    });
  }, [participants]);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: "100%", maxWidth: "900px", background: "#000", borderRadius: "12px", border: "1px solid #333", padding: "1.5rem", marginTop: "2rem" }}>
      <h2>Huddle Room: {roomName}</h2>
      
      {/* Participant Grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1.5rem", width: "100%", margin: "1.5rem 0" }}>
        
        {/* Local Participant */}
        <div style={{ background: "#111", borderRadius: "8px", border: "1px solid #444", padding: "1rem", display: "flex", flexDirection: "column", alignItems: "center" }}>
          <h4>You (Speaker)</h4>
          <div style={{ width: "150px", height: "150px", borderRadius: "50%", background: "#4A90E2", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "2rem" }}>
            👤
          </div>
        </div>

        {/* Remote Participants / Agent Avatars */}
        {participants.map((p) => (
          <div key={p.identity} style={{ background: "#111", borderRadius: "8px", border: "1px solid #444", padding: "1rem", display: "flex", flexDirection: "column", alignItems: "center" }}>
            <h4>Participant: {p.identity}</h4>
            <div 
              ref={(el) => { avatarRefs.current[p.identity] = el; }} 
              style={{ width: "150px", height: "150px" }} 
            />
          </div>
        ))}
      </div>

      <button 
        onClick={() => { room?.disconnect(); onDisconnect(); }}
        style={{ padding: "10px 20px", background: "#E24A4A", color: "white", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "16px" }}
      >
        Leave Huddle
      </button>
    </div>
  );
};
