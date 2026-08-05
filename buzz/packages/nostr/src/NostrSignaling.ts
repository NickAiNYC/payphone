import { generateSecretKey, getPublicKey, finalizeEvent } from 'nostr-tools/pure';

// High-compatibility NIP-44/17 Mock Cryptographer to support developer mock pubkeys
class MockCryptographer {
  static encrypt(plaintext: string): string {
    const bytes = new TextEncoder().encode(plaintext);
    const nonce = new Uint8Array(12);
    crypto.getRandomValues(nonce);
    const merged = new Uint8Array(nonce.length + bytes.length);
    merged.set(nonce);
    merged.set(bytes, nonce.length);
    return btoa(String.fromCharCode(...merged));
  }

  static decrypt(ciphertextB64: string): string {
    const binary = atob(ciphertextB64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    const payloadBytes = bytes.slice(12);
    return new TextDecoder().decode(payloadBytes);
  }
}

export class NostrSignaling {
  private socket: WebSocket;
  private pubkey: string;
  private privKey: Uint8Array;
  private onAnswerCallback?: (sdp: string) => void;
  private onIceCallback?: (candidate: any) => void;

  constructor(private relayUrl: string, private agentPubkey: string) {
    this.privKey = generateSecretKey();
    this.pubkey = getPublicKey(this.privKey);
    this.socket = new WebSocket(relayUrl);
    this.setupSocket();
  }

  private setupSocket() {
    this.socket.onopen = () => {
      console.log("[Nostr] Connected to relay:", this.relayUrl);
      const sub = ["REQ", "sub-call", {
        kinds: [13],
        "#p": [this.pubkey]
      }];
      this.socket.send(JSON.stringify(sub));
    };

    this.socket.onmessage = async (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg[0] === "EVENT") {
          const giftWrap = msg[2];
          if (giftWrap.kind === 13) {
            const decryptedSeal = MockCryptographer.decrypt(giftWrap.content);
            const seal = JSON.parse(decryptedSeal);
            
            const decryptedRumor = MockCryptographer.decrypt(seal.content);
            const rumor = JSON.parse(decryptedRumor);
            
            if (rumor.kind === 21001) {
              const content = JSON.parse(rumor.content);
              if (content.type === "answer" && this.onAnswerCallback) {
                this.onAnswerCallback(content.sdp);
              }
            } else if (rumor.kind === 21002 && this.onIceCallback) {
              const content = JSON.parse(rumor.content);
              this.onIceCallback(content.candidate);
            }
          }
        }
      } catch (err) {
        console.error("[Nostr] Error decrypting message:", err);
      }
    };
  }

  private wrapInGift(rumor: any): any {
    const encryptedRumor = MockCryptographer.encrypt(JSON.stringify(rumor));
    
    const sealTemplate = {
      kind: 14,
      created_at: Math.floor(Date.now() / 1000),
      tags: [],
      content: encryptedRumor
    };
    const seal = finalizeEvent(sealTemplate, this.privKey);
    
    const throwawayPriv = generateSecretKey();
    const encryptedSeal = MockCryptographer.encrypt(JSON.stringify(seal));
    
    const giftWrapTemplate = {
      kind: 13,
      created_at: Math.floor(Date.now() / 1000),
      tags: [["p", this.agentPubkey]],
      content: encryptedSeal
    };
    
    return finalizeEvent(giftWrapTemplate, throwawayPriv);
  }

  async sendOffer(sdp: string): Promise<void> {
    const offerPayload = {
      type: "offer",
      sdp: sdp,
      pubkey: this.pubkey
    };

    const rumor = {
      kind: 21001,
      pubkey: this.pubkey,
      created_at: Math.floor(Date.now() / 1000),
      tags: [["p", this.agentPubkey]],
      content: JSON.stringify(offerPayload)
    };

    const giftWrap = this.wrapInGift(rumor);
    this.socket.send(JSON.stringify(["EVENT", giftWrap]));
    console.log("[Nostr] NIP-17 Gift-wrapped offer sent to agent:", this.agentPubkey);
  }

  async sendIce(candidate: RTCIceCandidate): Promise<void> {
    const icePayload = {
      candidate: candidate.toJSON(),
      pubkey: this.pubkey
    };

    const rumor = {
      kind: 21002,
      pubkey: this.pubkey,
      created_at: Math.floor(Date.now() / 1000),
      tags: [["p", this.agentPubkey]],
      content: JSON.stringify(icePayload)
    };

    const giftWrap = this.wrapInGift(rumor);
    this.socket.send(JSON.stringify(["EVENT", giftWrap]));
  }

  onAnswer(callback: (sdp: string) => void) {
    this.onAnswerCallback = callback;
  }

  onIce(callback: (candidate: any) => void) {
    this.onIceCallback = callback;
  }
}
