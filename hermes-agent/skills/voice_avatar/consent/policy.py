class RawMediaPolicy:
    def __init__(self, consent_manager):
        self.consent = consent_manager

    async def can_process_raw_media(self, human_pubkey: str, agent_pubkey: str) -> bool:
        grant = await self.consent.fetch_grant(human_pubkey, agent_pubkey)
        if not grant:
            return False
        return grant.server_processing_opt_in
