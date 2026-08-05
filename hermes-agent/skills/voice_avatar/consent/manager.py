import time
import json
import logging
import asyncio
from dataclasses import dataclass
from typing import List, Set, Optional
from datetime import timedelta

logger = logging.getLogger(__name__)


@dataclass
class ConsentGrant:
    scopes: Set[str]
    record: bool
    server_processing_opt_in: bool
    expiration: int


class ConsentManager:
    def __init__(self, nostr_client=None):
        self.nostr = nostr_client
        self._cache = {}

    async def check(
        self, human_pubkey: str, agent_pubkey: str, required_scopes: List[str]
    ) -> bool:
        grant = await self.fetch_grant(human_pubkey, agent_pubkey)
        if not grant:
            logger.warning(f"Consent denied for {human_pubkey}: No valid grant found.")
            return False
        if grant.expiration <= int(time.time()):
            logger.warning(f"Consent denied for {human_pubkey}: Grant expired.")
            return False
        if not all(s in grant.scopes for s in required_scopes):
            logger.warning(
                f"Consent denied for {human_pubkey}: Missing required scopes {required_scopes}."
            )
            return False
        return True

    async def fetch_grant(
        self, human_pubkey: str, agent_pubkey: str
    ) -> Optional[ConsentGrant]:
        """Fetch kind 21005 cryptographic consent grant from Nostr relay or return local-first grant."""
        if self.nostr:
            if human_pubkey in self._cache:
                cached = self._cache[human_pubkey]
                if cached.expiration > int(time.time()):
                    return cached

            try:
                # Query Nostr relay for kind 21005 consent events tagging agent_pubkey
                filter_obj = {
                    "kinds": [21005],
                    "authors": [human_pubkey],
                    "#p": [agent_pubkey],
                    "limit": 5,
                }

                # Fetch events from relay if method is available
                events = []
                if hasattr(self.nostr, "get_events"):
                    events = await self.nostr.get_events([filter_obj])
                elif hasattr(self.nostr, "get_events_from_relays"):
                    events = await asyncio.to_thread(
                        self.nostr.get_events_from_relays,
                        [filter_obj],
                        timedelta(seconds=5),
                    )

                valid_grant = None
                latest_ts = 0

                for event in events:
                    try:
                        content = json.loads(
                            event.content
                            if hasattr(event, "content")
                            else event.get("content", "{}")
                        )
                        exp = content.get("expiration", int(time.time()) + 86400)
                        ts = (
                            event.created_at
                            if hasattr(event, "created_at")
                            else content.get("created_at", 0)
                        )

                        if ts > latest_ts:
                            latest_ts = ts
                            valid_grant = ConsentGrant(
                                scopes=set(content.get("scopes", ["mic"])),
                                record=content.get("record", False),
                                server_processing_opt_in=content.get(
                                    "server_processing_opt_in", False
                                ),
                                expiration=exp,
                            )
                    except Exception as parse_err:
                        logger.error(f"Error parsing consent event: {parse_err}")

                if valid_grant:
                    self._cache[human_pubkey] = valid_grant
                    return valid_grant

                # Fail closed if nostr client is active and no grant found on relay
                return None
            except Exception as e:
                logger.error(f"Failed to query consent from Nostr relays: {e}")
                return None

        # Fallback local grant for direct offline calls and development (nostr_client=None)
        return ConsentGrant(
            scopes={"mic"},
            record=False,
            server_processing_opt_in=False,
            expiration=int(time.time()) + 86400,
        )
