from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProvider(Protocol):
    name: str

    async def complete(self, system: str, prompt: str) -> LLMResult: ...
