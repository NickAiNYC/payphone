import React from "react";
import { ConsentGrant } from "@buzz/agent-consent/src/types";

const MicIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round">
    <rect x="9" y="2.5" width="6" height="11" rx="3" />
    <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" />
  </svg>
);

const CameraIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round">
    <rect x="2.5" y="6" width="14" height="12" rx="3" />
    <path d="M16.5 11l5-3v8l-5-3z" />
  </svg>
);

const ToolIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14.5 6.2a4 4 0 0 1 5.3 5.3l-8 8a4 4 0 0 1-5.3-5.3z" />
    <path d="M4.5 4.5l3 3" />
  </svg>
);

const LockIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round">
    <rect x="4.5" y="10" width="15" height="10.5" rx="3" />
    <path d="M8 10V7a4 4 0 0 1 8 0v3" />
  </svg>
);

export const ConsentSheet: React.FC<{
  agentName: string;
  scopes: string[];
  onApprove: (g: ConsentGrant) => void;
  onDeny?: () => void;
}> = ({ agentName, scopes, onApprove, onDeny }) => (
  <div className="scrim">
    <div className="sheet" role="dialog" aria-modal="true" aria-label={`${agentName} access request`}>
      <div className="grabber" />

      <h3>{agentName} wants to join</h3>
      <p className="sub">
        This grant is signed on your device and scoped to this agent alone.
        You can revoke it at any time.
      </p>

      <div className="scopes">
        {scopes.includes("mic") && (
          <div className="scope">
            <span className="ico">{MicIcon}</span>
            <span>
              Microphone
              <small>Speech is transcribed locally by Whisper</small>
            </span>
          </div>
        )}
        {scopes.includes("camera") && (
          <div className="scope">
            <span className="ico">{CameraIcon}</span>
            <span>
              Camera
              <small>Never enabled by default</small>
            </span>
          </div>
        )}
        {scopes.includes("tools_during_call") && (
          <div className="scope">
            <span className="ico">{ToolIcon}</span>
            <span>
              Run tools during the call
              <small>Each invocation is written to the call trace</small>
            </span>
          </div>
        )}
      </div>

      <div className="assurance">
        {LockIcon}
        <span>
          Recording is off. Raw audio never leaves your device — cloud processing
          stays blocked until you opt in explicitly.
        </span>
      </div>

      <div className="sheet-actions">
        <button
          className="btn filled"
          onClick={() =>
            onApprove({
              scopes: scopes as any,
              record: false,
              server_processing_opt_in: false,
              expiration: Date.now() + 86400000,
            })
          }
        >
          Allow for 24 hours
        </button>
        <button className="btn plain" onClick={onDeny}>
          Not now
        </button>
      </div>
    </div>
  </div>
);
