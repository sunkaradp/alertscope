from ..config import Settings
from .base import LLMProvider, LLMResult


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "bedrock":
        from .bedrock import BedrockProvider

        return BedrockProvider(settings)
    if settings.llm_provider == "vertex":
        from .vertex import VertexProvider

        return VertexProvider(settings)
    from .stub import StubProvider

    return StubProvider()


__all__ = ["LLMProvider", "LLMResult", "build_provider"]
