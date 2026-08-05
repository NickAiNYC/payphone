import React from "react";
import { ConsentGrant } from "@buzz/agent-consent/src/types";

export const ConsentSheet: React.FC<{
  agentName: string; scopes: string[]; onApprove: (g: ConsentGrant) => void;
}> = ({ agentName, scopes, onApprove }) => (
  <div className="modal-overlay">
    <div className="consent-sheet">
      <h3>{agentName} is requesting access:</h3>
      <ul>
        {scopes.includes("mic") && <li>🎤 Microphone</li>}
        {scopes.includes("camera") && <li>📹 Camera</li>}
        {scopes.includes("tools_during_call") && <li>🛠️ Run tools during call</li>}
      </ul>
      <p className="text-sm text-gray-500">Recording is OFF by default. Raw audio never leaves your device.</p>
      <button onClick={() => onApprove({ scopes: scopes as any, record: false, server_processing_opt_in: false, expiration: Date.now() + 86400000 })}>
        Allow Access
      </button>
    </div>
  </div>
);
