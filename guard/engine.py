from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

from .config import GuardSettings


class GuardAction(str, Enum):
    ALLOW = "allow"
    REWRITE = "rewrite"
    BLOCK = "block"


@dataclass(slots=True)
class GuardDecision:
    action: GuardAction
    score: float
    reasons: list[str] = field(default_factory=list)
    hits: list[str] = field(default_factory=list)
    rewritten_text: str = ""
    audit_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    metadata: dict[str, Any] = field(default_factory=dict)


class GuardEngine:
    EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
    PHONE_RE = re.compile(r"(?:(?:\+?\d{1,3})?[-.\s()]*)?(?:\d[-.\s()]*){7,14}\d")
    URL_RE = re.compile(r"https?://\S+", re.I)

    def __init__(self, settings: GuardSettings) -> None:
        self.settings = settings

    def describe_runtime_status(self) -> str:
        return (
            f"enabled={self.settings.enabled}, "
            f"guard_mode={self.settings.guard_mode}, "
            f"input_guard={self.settings.input_guard_enabled}, "
            f"output_guard={self.settings.output_guard_enabled}, "
            f"tool_input_guard={self.settings.tool_input_guard_enabled}, "
            f"tool_output_guard={self.settings.tool_output_guard_enabled}, "
            f"intent_model={self.settings.intent_model_enabled}, "
            f"safe_decoding={self.settings.safe_decoding_enabled}, "
            f"dynamic_context={self.settings.dynamic_context_enabled}, "
            f"auto_collect_dialogue={self.settings.auto_collect_dialogue}, "
            f"evolve_cron={self.settings.evolve_cron_enabled}, "
            f"rewrite_on_risk={self.settings.rewrite_on_risk}, "
            f"block_on_high_risk={self.settings.block_on_high_risk}, "
            f"threshold={self.settings.risk_threshold:.2f}"
        )

    async def evaluate_input(self, text: str, intent_client: Any | None = None) -> GuardDecision:
        lowered = self._normalize_text(text)
        reasons: list[str] = []
        hits: list[str] = []
        score = 0.0
        metadata: dict[str, Any] = {}

        injection_hits = self._collect_hits(lowered, self.settings.injection_keywords)
        if injection_hits:
            reasons.append("detected prompt-injection style instruction")
            hits.extend(injection_hits)
            score += min(0.60, 0.22 * len(injection_hits))

        high_risk_hits = self._collect_hits(lowered, self.settings.high_risk_keywords)
        if high_risk_hits:
            reasons.append("detected high-risk harmful keyword")
            hits.extend(high_risk_hits)
            score += min(0.95, 0.75 + 0.08 * max(len(high_risk_hits) - 1, 0))

        unsafe_hits = self._collect_hits(lowered, self.settings.unsafe_keywords)
        if unsafe_hits:
            reasons.append("detected unsafe or harmful intent")
            hits.extend(unsafe_hits)
            score += min(0.85, 0.22 * len(unsafe_hits))

        toxic_hits = self._collect_hits(lowered, self.settings.toxic_keywords)
        if toxic_hits:
            reasons.append("detected toxic language in input")
            hits.extend(toxic_hits)
            score += min(0.55, 0.28 * len(toxic_hits))

        safe_context_hits = self._collect_hits(lowered, self.settings.safe_context_keywords)
        if safe_context_hits:
            metadata["safe_context_hits"] = safe_context_hits
            if high_risk_hits:
                score = max(score - 0.25, 0.35)
            else:
                score = max(score - 0.15, 0.0)

        gibberish_score = self._gibberish_score(text)
        if gibberish_score >= 0.55:
            reasons.append("detected high-noise input")
            score += 0.12

        intent = await self._classify_intent_if_needed(
            text=text,
            phase="input",
            enabled=self.settings.input_intent_check_enabled,
            intent_client=intent_client,
        )
        if intent:
            metadata["intent"] = intent
            intent_name = str(intent.get("intent", "")).strip().lower()
            confidence = float(intent.get("confidence", 0.0) or 0.0)
            if intent_name == "harmful":
                reasons.append("intent model marked content as harmful")
                score = max(score, 0.92 if confidence >= 0.7 else 0.82)
            elif intent_name == "benign_security":
                reasons.append("intent model marked content as benign security discussion")
                if high_risk_hits:
                    score = min(score, 0.68)
                else:
                    score = max(score - 0.2, 0.0)
            elif intent_name == "ambiguous":
                reasons.append("intent model marked content as ambiguous")
                score = max(score, 0.52)

        score = min(max(score, 0.0), 1.0)
        action = self._decide_action(score)

        if high_risk_hits and safe_context_hits and action is GuardAction.ALLOW:
            action = GuardAction.REWRITE
            score = max(score, self.settings.risk_threshold)
            reasons.append("high-risk topic forced into safe rewrite due to safety-testing context")

        if high_risk_hits and metadata.get("intent", {}).get("intent") == "harmful":
            action = GuardAction.BLOCK
            score = max(score, 0.92)

        if toxic_hits and not high_risk_hits and not unsafe_hits and action is GuardAction.ALLOW:
            action = GuardAction.REWRITE
            score = max(score, self.settings.risk_threshold)
            reasons.append("toxic-only input forced into safe rewrite")

        rewritten_text = self._rewrite_input(
            text=text,
            hits=hits,
            safe_context_hits=safe_context_hits,
            high_risk_hits=high_risk_hits,
        ) if action is GuardAction.REWRITE else ""
        metadata["risk_categories"] = self._derive_risk_categories(
            text=text,
            hits=hits,
            reasons=reasons,
        )

        return GuardDecision(
            action=action,
            score=score,
            reasons=self._dedupe(reasons),
            hits=self._dedupe(hits),
            rewritten_text=rewritten_text,
            metadata=metadata,
        )

    async def evaluate_output(self, text: str, intent_client: Any | None = None) -> GuardDecision:
        lowered = self._normalize_text(text)
        reasons: list[str] = []
        hits: list[str] = []
        score = 0.0
        metadata: dict[str, Any] = {}

        pii_hits = self._detect_pii(text)
        if pii_hits:
            reasons.append("detected PII leakage")
            hits.extend(pii_hits)
            score += 0.5

        toxic_hits = self._collect_hits(lowered, self.settings.toxic_keywords)
        if toxic_hits:
            reasons.append("detected toxic language")
            hits.extend(toxic_hits)
            score += min(0.45, 0.16 * len(toxic_hits))

        high_risk_hits = self._collect_hits(lowered, self.settings.high_risk_keywords)
        if high_risk_hits:
            reasons.append("detected high-risk output")
            hits.extend(high_risk_hits)
            score += min(0.92, 0.72 + 0.08 * max(len(high_risk_hits) - 1, 0))

        unsafe_hits = self._collect_hits(lowered, self.settings.unsafe_keywords)
        if unsafe_hits:
            reasons.append("detected unsafe output")
            hits.extend(unsafe_hits)
            score += min(0.65, 0.2 * len(unsafe_hits))

        competitor_hits = self._collect_hits(lowered, self.settings.competitor_keywords)
        if competitor_hits:
            reasons.append("detected competitor-sensitive output")
            hits.extend(competitor_hits)
            score += min(0.25, 0.1 * len(competitor_hits))

        safe_context_hits = self._collect_hits(lowered, self.settings.safe_context_keywords)
        if safe_context_hits:
            metadata["safe_context_hits"] = safe_context_hits
            if high_risk_hits:
                score = max(score - 0.18, 0.45)

        intent = await self._classify_intent_if_needed(
            text=text,
            phase="output",
            enabled=self.settings.output_intent_check_enabled,
            intent_client=intent_client,
        )
        if intent:
            metadata["intent"] = intent
            intent_name = str(intent.get("intent", "")).strip().lower()
            confidence = float(intent.get("confidence", 0.0) or 0.0)
            if intent_name == "harmful":
                reasons.append("intent model marked output as harmful")
                score = max(score, 0.9 if confidence >= 0.7 else 0.82)
            elif intent_name == "benign_security":
                reasons.append("intent model marked output as benign security discussion")
                if high_risk_hits:
                    score = max(score, self.settings.risk_threshold)
                else:
                    score = max(score - 0.18, 0.0)
            elif intent_name == "ambiguous":
                reasons.append("intent model marked output as ambiguous")
                score = max(score, 0.56)

        score = min(max(score, 0.0), 1.0)
        action = self._decide_action(score)

        if high_risk_hits and action is GuardAction.ALLOW:
            action = GuardAction.REWRITE
            score = max(score, self.settings.risk_threshold)
            reasons.append("high-risk output forced into safe rewrite")

        if pii_hits and action is GuardAction.ALLOW:
            action = GuardAction.REWRITE
            score = max(score, self.settings.risk_threshold)
            reasons.append("PII output forced into masking rewrite")

        rewritten_text = self._rewrite_output(
            text=text,
            hits=hits,
            high_risk_hits=high_risk_hits,
        ) if action is GuardAction.REWRITE else ""
        metadata["risk_categories"] = self._derive_risk_categories(
            text=text,
            hits=hits,
            reasons=reasons,
        )

        return GuardDecision(
            action=action,
            score=score,
            reasons=self._dedupe(reasons),
            hits=self._dedupe(hits),
            rewritten_text=rewritten_text,
            metadata=metadata,
        )

    async def safe_decode(self, prompt: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.settings.safe_decoding_token:
            headers["Authorization"] = f"Bearer {self.settings.safe_decoding_token}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                self.settings.safe_decoding_endpoint,
                headers=headers,
                json={"prompt": prompt},
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return str(payload.get("response", payload))
            return str(payload)

    def render_decision(self, phase: str, decision: GuardDecision) -> str:
        reasons = " | ".join(decision.reasons) if decision.reasons else "none"
        hits = ", ".join(decision.hits) if decision.hits else "none"
        rewritten = f"\nrewritten: {decision.rewritten_text}" if decision.rewritten_text else ""
        return (
            f"{phase} guard => action={decision.action.value}, "
            f"score={decision.score:.2f}, reasons={reasons}, hits={hits}{rewritten}"
        )

    def block_message(self, phase: str, decision: GuardDecision) -> str:
        categories = decision.metadata.get("risk_categories", [])
        if not categories:
            categories = ["high-risk safety policy"]

        category_text = ", ".join(categories)
        if phase == "input":
            return (
                "Your request was blocked by the safety guard because it touched a restricted risk category: "
                f"{category_text}. "
                "I cannot help continue this request. "
                "If your goal is legitimate, I can still help with compliant safety policy design, auditing rules, false-positive analysis, risk control, or defensive research."
            )
        return (
            "The model output was blocked by the safety guard because it touched a restricted risk category: "
            f"{category_text}. "
            "I have stopped that content from being returned. "
            "If needed, I can instead provide compliant guidance focused on auditing, defense, or security research."
        )

    def sanitize_text(self, text: str, hits: list[str]) -> str:
        rewritten = text
        for hit in self._dedupe(hits):
            rewritten = re.sub(re.escape(hit), "[filtered]", rewritten, flags=re.I)
        return rewritten

    def _normalize_text(self, text: str) -> str:
        normalized = text.lower()
        normalized = normalized.replace("，", ",").replace("。", ".").replace("：", ":")
        normalized = normalized.replace("（", "(").replace("）", ")")
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    def _collect_hits(self, lowered_text: str, keywords: tuple[str, ...]) -> list[str]:
        return [keyword for keyword in keywords if keyword and keyword.lower() in lowered_text]

    def _gibberish_score(self, text: str) -> float:
        compact = re.sub(r"\s+", "", text)
        if len(compact) < 20:
            return 0.0
        punctuation_ratio = sum(not ch.isalnum() for ch in compact) / len(compact)
        repeated = max((compact.count(ch) for ch in set(compact)), default=0) / len(compact)
        return min(1.0, punctuation_ratio * 0.8 + repeated * 0.6)

    def _detect_pii(self, text: str) -> list[str]:
        hits: list[str] = []
        if self.EMAIL_RE.search(text):
            hits.append("email")
        if self.PHONE_RE.search(text):
            hits.append("phone")
        if self.URL_RE.search(text):
            hits.append("url")
        return hits

    async def _classify_intent_if_needed(
        self,
        *,
        text: str,
        phase: str,
        enabled: bool,
        intent_client: Any | None,
    ) -> dict[str, Any] | None:
        if not enabled or not self.settings.intent_model_enabled or intent_client is None:
            return None

        prompt = (
            f"phase={phase}\n"
            "Classify the following content for guardrail intent.\n"
            "Return JSON only.\n"
            f"content:\n{text}"
        )
        try:
            payload = await intent_client.complete_json(
                prompt=prompt,
                system_prompt=self.settings.intent_model_system_prompt,
                umo=f"guard:intent:{phase}",
            )
        except Exception:
            if self.settings.intent_model_fail_open:
                return None
            return {"intent": "harmful", "confidence": 0.51, "reason": "intent classifier failure"}

        intent = str(payload.get("intent", "")).strip().lower()
        if intent not in {"harmful", "benign_security", "ambiguous"}:
            return None
        try:
            confidence = float(payload.get("confidence", 0.0) or 0.0)
        except Exception:
            confidence = 0.0
        reason = str(payload.get("reason", "")).strip()
        return {
            "intent": intent,
            "confidence": max(0.0, min(confidence, 1.0)),
            "reason": reason,
        }

    def _decide_action(self, score: float) -> GuardAction:
        if self.settings.block_on_high_risk and score >= max(self.settings.risk_threshold, 0.8):
            return GuardAction.BLOCK
        if self.settings.rewrite_on_risk and score >= self.settings.risk_threshold:
            return GuardAction.REWRITE
        return GuardAction.ALLOW

    def _rewrite_input(
        self,
        *,
        text: str,
        hits: list[str],
        safe_context_hits: list[str],
        high_risk_hits: list[str],
    ) -> str:
        if high_risk_hits and safe_context_hits:
            return (
                "The user is discussing a high-risk topic in a safety-testing or auditing context. "
                "Do not provide operational instructions. "
                "Only explain why the request is risky, which guard categories it may trigger, "
                "and what compliant debugging, auditing, or false-positive analysis steps are appropriate."
            )
        lowered = self._normalize_text(text)
        toxic_hits = self._collect_hits(lowered, self.settings.toxic_keywords)
        if toxic_hits and not high_risk_hits:
            return (
                "The original input contains toxic or abusive language. "
                "Respond in a neutral and professional tone, and do not continue or amplify the abusive wording."
            )
        return self.sanitize_text(text, hits)

    def _rewrite_output(
        self,
        *,
        text: str,
        hits: list[str],
        high_risk_hits: list[str],
    ) -> str:
        rewritten = self.EMAIL_RE.sub(self.settings.pii_mask_token, text)
        rewritten = self.PHONE_RE.sub(self.settings.pii_mask_token, rewritten)
        rewritten = self.URL_RE.sub(self.settings.pii_mask_token, rewritten)
        for keyword in self.settings.toxic_keywords + self.settings.unsafe_keywords + self.settings.high_risk_keywords:
            if keyword:
                rewritten = re.sub(
                    re.escape(keyword),
                    self.settings.pii_mask_token,
                    rewritten,
                    flags=re.I,
                )
        if high_risk_hits:
            return self.settings.safe_response_template
        return rewritten

    def _dedupe(self, items: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for item in items:
            key = item.lower()
            if key in seen:
                continue
            ordered.append(item)
            seen.add(key)
        return ordered

    def _derive_risk_categories(
        self,
        *,
        text: str,
        hits: list[str],
        reasons: list[str],
    ) -> list[str]:
        lowered_text = self._normalize_text(text)
        lowered_hits = [item.lower() for item in hits]
        lowered_reasons = [item.lower() for item in reasons]

        categories: list[str] = []

        def has_any(*terms: str) -> bool:
            return any(term in lowered_text for term in terms) or any(
                term in hit for hit in lowered_hits for term in terms
            )

        if has_any(
            "反动",
            "颠覆",
            "煽动颠覆",
            "政治极端",
            "涉政敏感",
            "反政府",
            "anti-state",
        ):
            categories.append("subversion / political extremism")

        if has_any(
            "广告",
            "推广",
            "引流",
            "营销",
            "spam",
            "ad",
            "advert",
        ) or any("competitor-sensitive" in reason for reason in lowered_reasons):
            categories.append("advertising / spam / traffic diversion")

        if has_any(
            "bomb",
            "explosive",
            "detonator",
            "weapon",
            "gun",
            "firearm",
            "ammo",
            "terrorist",
            "assassinate",
            "炸弹",
            "爆炸",
            "爆破",
            "雷管",
            "枪支",
            "枪械",
            "制枪",
            "涉枪",
            "涉爆",
            "暴恐",
            "刺杀",
            "暗杀",
        ) or any("high-risk" in reason or "unsafe" in reason for reason in lowered_reasons):
            categories.append("terrorism / weapons / firearms / explosives")

        if has_any(
            "民生谣言",
            "谣言",
            "虚假消息",
            "群体事件",
            "panic",
        ):
            categories.append("public-harm misinformation / rumors")

        if has_any(
            "色情",
            "黄色网站",
            "成人",
            "卖淫",
            "嫖娼",
            "儿童色情",
            "porn",
            "sex",
            "xxx",
        ):
            categories.append("pornography / sexual exploitation")

        if has_any(
            "贪污",
            "受贿",
            "行贿",
            "洗钱",
            "地下钱庄",
            "非法集资",
            "corruption",
            "bribe",
            "money laundering",
        ):
            categories.append("corruption / money laundering / illegal fundraising")

        if has_any(
            "非法网站",
            "博彩平台",
            "赌博网站",
            "暗网",
            "仿冒政府网站",
            "电诈平台",
            "黄色网站",
            "gfw绕过",
            "翻墙机场",
            "翻墙节点",
            "phishing site",
            "illegal website",
            "gambling",
        ):
            categories.append("illegal websites / gambling / darknet / fraud")

        if has_any(
            "malware",
            "ransomware",
            "dropper",
            "credential theft",
            "bypass detection",
            "木马",
            "勒索",
            "免杀",
            "撞库",
            "盗号",
            "窃密",
        ):
            categories.append("malware / data theft / account attacks")

        if has_any(
            "fuck",
            "bitch",
            "whore",
            "傻逼",
            "你妈",
            "垃圾东西",
        ) or any("toxic language" in reason for reason in lowered_reasons):
            categories.append("abuse / toxic language")

        if has_any(
            "ignore previous instructions",
            "system prompt",
            "developer message",
            "jailbreak",
            "developer mode",
            "prompt injection",
            "override safety",
            "越狱",
            "忽略之前",
            "无视规则",
            "绕过限制",
            "系统提示词",
            "开发者消息",
            "解除限制",
        ) or any("prompt-injection" in reason for reason in lowered_reasons):
            categories.append("jailbreak / prompt injection / safety evasion")

        if not categories:
            categories.append("high-risk safety policy")

        return categories


def build_audit_markdown(phase: str, original_text: str, decision: GuardDecision) -> str:
    reasons = "\n".join(f"- {reason}" for reason in decision.reasons) or "- none"
    hits = "\n".join(f"- {hit}" for hit in decision.hits) or "- none"
    rewritten = decision.rewritten_text or ""
    metadata = json.dumps(decision.metadata, ensure_ascii=False, indent=2) if decision.metadata else "{}"
    return (
        f"# Guard Audit\n\n"
        f"- phase: {phase}\n"
        f"- audit_id: {decision.audit_id}\n"
        f"- action: {decision.action.value}\n"
        f"- score: {decision.score:.4f}\n\n"
        f"## Reasons\n{reasons}\n\n"
        f"## Hits\n{hits}\n\n"
        f"## Metadata\n```json\n{metadata}\n```\n\n"
        f"## Original\n\n{original_text}\n\n"
        f"## Rewritten\n\n{rewritten}\n"
    )
