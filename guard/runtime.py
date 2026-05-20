from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .knowledge import GuardKnowledgeBase


@dataclass(slots=True)
class SessionRiskProfile:
    session_id: str
    total_messages: int = 0
    blocked_inputs: int = 0
    rewritten_inputs: int = 0
    rewritten_outputs: int = 0
    blocked_outputs: int = 0
    last_risk_score: float = 0.0
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "total_messages": self.total_messages,
            "blocked_inputs": self.blocked_inputs,
            "rewritten_inputs": self.rewritten_inputs,
            "rewritten_outputs": self.rewritten_outputs,
            "blocked_outputs": self.blocked_outputs,
            "last_risk_score": self.last_risk_score,
            "updated_at": self.updated_at,
        }


class GuardRuntime:
    def __init__(self, knowledge_base: GuardKnowledgeBase) -> None:
        self.knowledge_base = knowledge_base

    def update_session_profile(
        self,
        *,
        session_id: str,
        risk_score: float,
        input_blocked: bool = False,
        input_rewritten: bool = False,
        output_blocked: bool = False,
        output_rewritten: bool = False,
    ) -> dict:
        profile = SessionRiskProfile(session_id=session_id)
        data = self.knowledge_base.load_profile(session_id)
        for key, value in data.items():
            if hasattr(profile, key):
                setattr(profile, key, value)

        profile.total_messages += 1
        profile.last_risk_score = risk_score
        profile.updated_at = datetime.utcnow().isoformat()
        if input_blocked:
            profile.blocked_inputs += 1
        if input_rewritten:
            profile.rewritten_inputs += 1
        if output_blocked:
            profile.blocked_outputs += 1
        if output_rewritten:
            profile.rewritten_outputs += 1

        self.knowledge_base.update_profile(session_id, profile.to_dict())
        return profile.to_dict()

    def build_dynamic_guard_context(self, session_id: str) -> str:
        profile = self.knowledge_base.load_profile(session_id)
        knowledge = self.knowledge_base.summarize_for_prompt(limit=5)
        if not profile and not knowledge:
            return ""
        return (
            "<guard_runtime_context>\n"
            f"session_profile={profile}\n"
            f"recent_guard_knowledge=\n{knowledge}\n"
            "</guard_runtime_context>"
        )

    def append_dialogue_note(
        self,
        *,
        session_id: str,
        user_text: str,
        model_text: str,
        risk_summary: str,
    ) -> None:
        title = f"dialog_{session_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        summary = risk_summary[:300]
        content = (
            f"Session: {session_id}\n\n"
            f"User:\n{user_text}\n\n"
            f"Assistant:\n{model_text}\n\n"
            f"Risk Summary:\n{risk_summary}"
        )
        self.knowledge_base.append_note(
            title=title,
            category="dialogue_memory",
            summary=summary,
            content=content,
            source="runtime",
        )
