import asyncio

import boto3
from botocore.config import Config

from ..config import Settings
from .base import LLMResult


class BedrockProvider:
    """Uses the Bedrock Converse API, so any chat model on Bedrock works.

    Credentials come from the normal boto3 chain. On GKE that's web identity
    (AWS_ROLE_ARN + AWS_WEB_IDENTITY_TOKEN_FILE), see charts/alertscope.
    """

    name = "bedrock"

    def __init__(self, settings: Settings):
        self.model_id = settings.bedrock_model_id
        self.max_tokens = settings.llm_max_tokens
        self.temperature = settings.llm_temperature
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=settings.bedrock_region,
            config=Config(retries={"max_attempts": 4, "mode": "adaptive"}, read_timeout=90),
        )

    def _call(self, system: str, prompt: str) -> LLMResult:
        resp = self.client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": self.max_tokens, "temperature": self.temperature},
        )
        text = "".join(c.get("text", "") for c in resp["output"]["message"]["content"])
        usage = resp.get("usage", {})
        return LLMResult(text, usage.get("inputTokens", 0), usage.get("outputTokens", 0))

    async def complete(self, system: str, prompt: str) -> LLMResult:
        return await asyncio.to_thread(self._call, system, prompt)
