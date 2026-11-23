from google import genai
from google.genai import types

from ..config import Settings
from .base import LLMResult


class VertexProvider:
    """Gemini on Vertex AI. Auth is Application Default Credentials / GKE Workload Identity."""

    name = "vertex"

    def __init__(self, settings: Settings):
        self.model = settings.vertex_model
        self.client = genai.Client(
            vertexai=True,
            project=settings.vertex_project or None,
            location=settings.vertex_location,
        )
        self.max_tokens = settings.llm_max_tokens
        self.temperature = settings.llm_temperature

    async def complete(self, system: str, prompt: str) -> LLMResult:
        resp = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
                response_mime_type="application/json",
            ),
        )
        usage = resp.usage_metadata
        return LLMResult(
            resp.text or "",
            getattr(usage, "prompt_token_count", 0) or 0,
            getattr(usage, "candidates_token_count", 0) or 0,
        )
