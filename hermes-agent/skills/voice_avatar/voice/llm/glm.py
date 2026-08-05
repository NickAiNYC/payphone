import os
from typing import AsyncIterator
from openai import AsyncOpenAI
from .base import LLMProvider


class GLM5Provider(LLMProvider):
    """Universal OpenAI-compatible LLM provider.
    Supports OpenAI (GPT-4o), Groq, Ollama, DeepSeek, OpenRouter, GLM-5, vLLM, and local endpoints.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}

        # Detect provider endpoints and API keys
        api_key = (
            self.config.get("api_key")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("GROQ_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("GLM_API_KEY")
            or "ollama_key"
        )

        api_base = self.config.get("api_base")
        if not api_base:
            if os.environ.get("GROQ_API_KEY") or self.config.get("provider") == "groq":
                api_base = "https://api.groq.com/openai/v1"
            elif (
                os.environ.get("DEEPSEEK_API_KEY")
                or self.config.get("provider") == "deepseek"
            ):
                api_base = "https://api.deepseek.com/v1"
            elif (
                os.environ.get("OPENROUTER_API_KEY")
                or self.config.get("provider") == "openrouter"
            ):
                api_base = "https://openrouter.ai/api/v1"
            elif (
                os.environ.get("OLLAMA_HOST") or self.config.get("provider") == "ollama"
            ):
                host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
                api_base = f"{host}/v1" if not host.endswith("/v1") else host
            else:
                api_base = (
                    os.environ.get("LLM_API_BASE")
                    or os.environ.get("GLM_API_BASE")
                    or os.environ.get("OPENAI_API_BASE")
                    or "https://api.openai.com/v1"
                )

        # Detect model choice
        self.model = (
            self.config.get("model")
            or os.environ.get("LLM_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or os.environ.get("GLM_MODEL")
            or (
                "llama-3.3-70b-versatile"
                if "groq" in api_base
                else "gpt-4o-mini" if "openai" in api_base else "glm-5"
            )
        )

        self.client = AsyncOpenAI(api_key=api_key, base_url=api_base)
        print(f"[LLM] Initialized provider ({self.model}) at base URL: {api_base}")

    async def generate_stream(self, prompt: str) -> AsyncIterator[str]:
        system_prompt = (
            "You are a helpful, real-time voice assistant. "
            "Keep responses conversational, short, and friendly. "
            "Instruct the voice synthesis to change emotion by inserting inline tags in the format "
            "<emotion:happy|0.85> or <emotion:sad|0.9> when your conversational tone changes. "
            "Do not output markdown format; only clean text and emotion tags."
        )

        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                stream=True,
            )

            async for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        except Exception as e:
            print(f"[LLM] Error in streaming generation ({self.model}): {e}")
            yield f"Error: {e}"


# Export alias for convenience
OpenAIProvider = GLM5Provider
