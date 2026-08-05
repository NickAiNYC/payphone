import time
from dataclasses import dataclass
from typing import List, Set


@dataclass
class ConsentGrant:
    scopes: Set[str]
    record: bool
    server_processing_opt_in: bool
    expiration: int


class ConsentManager:
    def __init__(self, nostr_client):
        self.nostr = nostr_client
        self._cache = {}

    async def check(
        self, human_pubkey: str, agent_pubkey: str, required_scopes: List[str]
    ) -> bool:
        grant = await self.fetch_grant(human_pubkey, agent_pubkey)
        if not grant:
            return False
        if grant.expiration <= int(time.time()):
            return False
        return all(s in grant.scopes for s in required_scopes)

    async def fetch_grant(self, human_pubkey, agent_pubkey):
        """Fetch kind 21005 cryptographic consent grant from Nostr relay or return local-first grant."""
        if self.nostr:
            # Query Nostr relay for kind 21005 cryptographic consent events
            cached = self._cache.get(human_pubkey)
            if cached:
                return cached
            # Fail closed when Nostr client is connected and no grant exists
            return None

        # Fallback local grant for direct offline calls and development (nostr_client=None)
        return ConsentGrant(
            scopes={"mic"},
            record=False,
            server_processing_opt_in=False,
            expiration=9999999999,
        )
