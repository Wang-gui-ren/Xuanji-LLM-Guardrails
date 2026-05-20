from __future__ import annotations

import json

import httpx

from astrbot.api import logger
from astrbot.core.agent.message import Message, SystemMessageSegment, UserMessageSegment

from .config import GuardSettings


class GuardLLMClient:
    def __init__(self, plugin_context, settings: GuardSettings) -> None:
        self.context = plugin_context
        self.settings = settings

    async def complete_json(
        self,
        *,
        prompt: str,
        system_prompt: str,
        umo: str,
    ) -> dict:
        content = await self.complete_text(
            prompt=prompt,
            system_prompt=system_prompt,
            umo=umo,
        )
        try:
            return json.loads(content)
        except Exception as exc:
            raise ValueError(f"LLM did not return valid JSON: {exc}; content={content[:500]}") from exc

    async def complete_text(
        self,
        *,
        prompt: str,
        system_prompt: str,
        umo: str,
    ) -> str:
        if self.settings.llm_mode == "openai_compatible_api":
            return await self._complete_via_openai_api(prompt=prompt, system_prompt=system_prompt)
        return await self._complete_via_astrbot_provider(prompt=prompt, system_prompt=system_prompt, umo=umo)

    async def _complete_via_astrbot_provider(
        self,
        *,
        prompt: str,
        system_prompt: str,
        umo: str,
    ) -> str:
        provider_id = self.settings.astrbot_provider_id or await self.context.get_current_chat_provider_id(umo)
        messages: list[Message] = [
            SystemMessageSegment(content=system_prompt),
            UserMessageSegment(content=prompt),
        ]
        resp = await self.context.llm_generate(
            chat_provider_id=provider_id,
            contexts=messages,
            temperature=self.settings.llm_temperature,
        )
        return resp.completion_text or ""

    async def _complete_via_openai_api(
        self,
        *,
        prompt: str,
        system_prompt: str,
    ) -> str:
        if not self.settings.openai_base_url or not self.settings.openai_api_key or not self.settings.openai_model:
            raise ValueError("openai_compatible_api mode requires openai_base_url, openai_api_key and openai_model")

        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.settings.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.settings.llm_temperature,
        }
        url = self.settings.openai_base_url.rstrip("/") + "/chat/completions"
        async with httpx.AsyncClient(timeout=float(self.settings.openai_timeout_seconds)) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            payload = response.json()
        try:
            return payload["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("unexpected openai-compatible payload: %s", payload)
            raise ValueError(f"unexpected openai-compatible response: {exc}") from exc
