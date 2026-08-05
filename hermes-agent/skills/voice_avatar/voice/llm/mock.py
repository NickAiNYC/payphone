import asyncio
from typing import AsyncIterator
from .base import LLMProvider


class MockLLM(LLMProvider):
    def __init__(self, config: dict = None):
        self.config = config or {}

    async def generate_stream(self, prompt: str) -> AsyncIterator[str]:
        response_text = "Hello! <emotion:happy|0.95> I am doing wonderfully well. How can I help you today?"
        # Split into small chunks to simulate real-time token streaming
        chunks = [response_text[i : i + 4] for i in range(0, len(response_text), 4)]
        for chunk in chunks:
            yield chunk
            await asyncio.sleep(0.05)  # Simulate token generation latency
