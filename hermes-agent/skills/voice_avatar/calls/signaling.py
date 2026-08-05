import json, time, secrets


class NostrSignaling:
    def __init__(self, nostr_client, nostr_pubkey: str):
        self.nostr = nostr_client
        self.pubkey = nostr_pubkey

    async def send_invite(
        self, to_pubkey: str, offer_sdp: str, media_types: list
    ) -> str:
        call_id = secrets.token_hex(8)
        content = json.dumps(
            {
                "call_id": call_id,
                "kind": "1:1",
                "offer_sdp": offer_sdp,
                "media_types": media_types,
            }
        )
        await self.nostr.publish_gift_wrap(to_pubkey, 21001, content)
        return call_id

    async def send_ice(self, call_id: str, candidate: dict):
        content = json.dumps({"call_id": call_id, "candidate": candidate})
        tags = [["e", call_id], ["expiration", str(int(time.time()) + 60)]]
        await self.nostr.publish_ephemeral(21002, content, tags)

    async def send_hangup(
        self, call_id: str, to_pubkey: str, reason: str = "agent_initiated"
    ):
        content = json.dumps({"call_id": call_id, "status": "hangup", "reason": reason})
        await self.nostr.publish_gift_wrap(to_pubkey, 21004, content)

    async def send_summary(self, call_id: str, to_pubkey: str, summary: dict):
        content = json.dumps({"call_id": call_id, **summary})
        await self.nostr.publish_gift_wrap(to_pubkey, 21003, content)
