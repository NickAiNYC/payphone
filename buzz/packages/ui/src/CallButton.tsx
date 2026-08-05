import React from "react";

export const CallButton: React.FC<{ agentPubkey: string }> = ({ agentPubkey }) => {
  const [needsConsent, setNeedsConsent] = React.useState(false);

  const handleClick = async () => {
    const hasConsent = false; // Abstracted check
    if (!hasConsent) {
      setNeedsConsent(true);
      return;
    }
    // startCall(agentPubkey, { video: false });
  };

  if (needsConsent) return <div>Consent Required UI</div>;

  return (
    <button onClick={handleClick}>
      📞 Call Agent
    </button>
  );
};
