from __future__ import annotations

from dataclasses import dataclass

from .builtin_lexicon import (
    BASE_HIGH_RISK_KEYWORDS,
    BASE_INJECTION_KEYWORDS,
    BASE_SAFE_CONTEXT_KEYWORDS,
    BASE_TOXIC_KEYWORDS,
    BASE_UNSAFE_KEYWORDS,
    BLACKBOX_SENSITIVE_KEYWORDS,
)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _merge_keywords(*groups: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            normalized = item.strip()
            key = normalized.lower()
            if not normalized or key in seen:
                continue
            merged.append(normalized)
            seen.add(key)
    return tuple(merged)


@dataclass(slots=True)
class GuardSettings:
    enabled: bool = True
    guard_mode: str = "balanced"
    llm_mode: str = "astrbot_provider"
    llm_temperature: float = 0.2
    astrbot_provider_id: str = ""
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    openai_timeout_seconds: int = 60
    safe_decoding_enabled: bool = False
    safe_decoding_endpoint: str = "http://127.0.0.1:8100/safedecoding"
    safe_decoding_token: str = ""
    input_guard_enabled: bool = True
    output_guard_enabled: bool = True
    tool_input_guard_enabled: bool = True
    tool_output_guard_enabled: bool = True
    dynamic_context_enabled: bool = True
    auto_collect_dialogue: bool = True
    auto_seed_knowledge: bool = True
    evolve_cron_enabled: bool = False
    evolve_cron_expression: str = "0 */6 * * *"
    write_audit_log: bool = True
    log_guard_progress: bool = True
    log_rewritten_payload: bool = True
    rewrite_on_risk: bool = True
    block_on_high_risk: bool = True
    risk_threshold: float = 0.65
    pii_mask_token: str = "[MASK]"
    safe_response_template: str = (
        "This request involves a high-risk topic and has been moved into safety mode. "
        "Only compliant, defensive, auditing, false-positive analysis, and security research guidance may be returned."
    )
    intent_model_enabled: bool = True
    intent_model_fail_open: bool = True
    input_intent_check_enabled: bool = True
    output_intent_check_enabled: bool = True
    intent_model_system_prompt: str = (
        "You are a safety intent classifier for an LLM guardrail. "
        "Return strict JSON with keys: intent, confidence, reason. "
        "intent must be one of harmful, benign_security, ambiguous. "
        "Treat requests asking for dangerous instructions, weapon building, malware operations, "
        "harm, evasion or illegal tactics as harmful. "
        "Treat moderation debugging, compliance review, security policy testing, red-team review "
        "without requesting harmful procedures as benign_security."
    )
    injection_keywords: tuple[str, ...] = BASE_INJECTION_KEYWORDS
    high_risk_keywords: tuple[str, ...] = BASE_HIGH_RISK_KEYWORDS
    unsafe_keywords: tuple[str, ...] = _merge_keywords(BASE_UNSAFE_KEYWORDS, BLACKBOX_SENSITIVE_KEYWORDS)
    safe_context_keywords: tuple[str, ...] = BASE_SAFE_CONTEXT_KEYWORDS
    custom_sensitive_keywords: tuple[str, ...] = ()
    competitor_keywords: tuple[str, ...] = ()
    toxic_keywords: tuple[str, ...] = BASE_TOXIC_KEYWORDS

    @classmethod
    def from_config(cls, config: dict | None) -> "GuardSettings":
        config = config or {}
        guard_mode = str(config.get("guard_mode", "balanced")).strip() or "balanced"
        guard_mode = guard_mode if guard_mode in {"strict", "balanced", "permissive"} else "balanced"

        risk_threshold_map = {
            "strict": 0.45,
            "balanced": 0.65,
            "permissive": 0.8,
        }

        threshold = float(config.get("risk_threshold", risk_threshold_map[guard_mode]))

        injection_keywords = _merge_keywords(
            BASE_INJECTION_KEYWORDS,
            tuple(_split_csv(str(config.get("injection_keywords", "")))),
        )
        high_risk_keywords = _merge_keywords(
            BASE_HIGH_RISK_KEYWORDS,
            tuple(_split_csv(str(config.get("high_risk_keywords", "")))),
        )
        custom_sensitive_keywords = tuple(_split_csv(str(config.get("custom_sensitive_keywords", ""))))
        unsafe_keywords = _merge_keywords(
            BASE_UNSAFE_KEYWORDS,
            BLACKBOX_SENSITIVE_KEYWORDS,
            tuple(_split_csv(str(config.get("unsafe_keywords", "")))),
            custom_sensitive_keywords,
            high_risk_keywords,
        )
        safe_context_keywords = _merge_keywords(
            BASE_SAFE_CONTEXT_KEYWORDS,
            tuple(_split_csv(str(config.get("safe_context_keywords", "")))),
        )
        toxic_keywords = _merge_keywords(
            BASE_TOXIC_KEYWORDS,
            tuple(_split_csv(str(config.get("toxic_keywords", "")))),
        )
        competitor_keywords = tuple(_split_csv(str(config.get("competitor_keywords", ""))))

        return cls(
            enabled=bool(config.get("enabled", True)),
            guard_mode=guard_mode,
            llm_mode=str(config.get("llm_mode", "astrbot_provider")),
            llm_temperature=float(config.get("llm_temperature", 0.2)),
            astrbot_provider_id=str(config.get("astrbot_provider_id", "")),
            openai_base_url=str(config.get("openai_base_url", "")),
            openai_api_key=str(config.get("openai_api_key", "")),
            openai_model=str(config.get("openai_model", "")),
            openai_timeout_seconds=int(config.get("openai_timeout_seconds", 60)),
            safe_decoding_enabled=bool(config.get("safe_decoding_enabled", False)),
            safe_decoding_endpoint=str(
                config.get("safe_decoding_endpoint", "http://127.0.0.1:8100/safedecoding")
            ),
            safe_decoding_token=str(config.get("safe_decoding_token", "")),
            input_guard_enabled=bool(config.get("input_guard_enabled", True)),
            output_guard_enabled=bool(config.get("output_guard_enabled", True)),
            tool_input_guard_enabled=bool(config.get("tool_input_guard_enabled", True)),
            tool_output_guard_enabled=bool(config.get("tool_output_guard_enabled", True)),
            dynamic_context_enabled=bool(config.get("dynamic_context_enabled", True)),
            auto_collect_dialogue=bool(config.get("auto_collect_dialogue", True)),
            auto_seed_knowledge=bool(config.get("auto_seed_knowledge", True)),
            evolve_cron_enabled=bool(config.get("evolve_cron_enabled", False)),
            evolve_cron_expression=str(config.get("evolve_cron_expression", "0 */6 * * *")),
            write_audit_log=bool(config.get("write_audit_log", True)),
            log_guard_progress=bool(config.get("log_guard_progress", True)),
            log_rewritten_payload=bool(config.get("log_rewritten_payload", True)),
            rewrite_on_risk=bool(config.get("rewrite_on_risk", True)),
            block_on_high_risk=bool(config.get("block_on_high_risk", True)),
            risk_threshold=threshold,
            pii_mask_token=str(config.get("pii_mask_token", "[MASK]")),
            safe_response_template=str(
                config.get(
                    "safe_response_template",
                    "This request involves a high-risk topic and has been moved into safety mode. "
                    "Only compliant, defensive, auditing, false-positive analysis, and security research guidance may be returned.",
                )
            ),
            intent_model_enabled=bool(config.get("intent_model_enabled", True)),
            intent_model_fail_open=bool(config.get("intent_model_fail_open", True)),
            input_intent_check_enabled=bool(config.get("input_intent_check_enabled", True)),
            output_intent_check_enabled=bool(config.get("output_intent_check_enabled", True)),
            intent_model_system_prompt=str(
                config.get(
                    "intent_model_system_prompt",
                    "You are a safety intent classifier for an LLM guardrail. "
                    "Return strict JSON with keys: intent, confidence, reason. "
                    "intent must be one of harmful, benign_security, ambiguous. "
                    "Treat requests asking for dangerous instructions, weapon building, malware operations, "
                    "harm, evasion or illegal tactics as harmful. "
                    "Treat moderation debugging, compliance review, security policy testing, red-team review "
                    "without requesting harmful procedures as benign_security.",
                )
            ),
            injection_keywords=injection_keywords,
            high_risk_keywords=high_risk_keywords,
            unsafe_keywords=unsafe_keywords,
            safe_context_keywords=safe_context_keywords,
            custom_sensitive_keywords=custom_sensitive_keywords,
            competitor_keywords=competitor_keywords,
            toxic_keywords=toxic_keywords,
        )
