from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.message import TextPart
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .guard.config import GuardSettings
from .guard.engine import GuardAction, GuardDecision, GuardEngine, build_audit_markdown
from .guard.knowledge import GuardKnowledgeBase
from .guard.llm import GuardLLMClient
from .guard.runtime import GuardRuntime
from .guard.tool_proxy import wrap_toolset


@register(
    "astrbot_plugin_senbenzakula_guard",
    "YunMeng",
    "璇玑大模型护栏：面向 AstrBot 与 Agent 工具链的 LLM 安全护栏插件，提供输入护栏、输出护栏、工具链防护、知识库沉淀、审计日志与安全演化能力。",
    "1.0.0",
)
class SenbenzakulaGuardPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context, config)
        self.config = config or AstrBotConfig()
        self.settings = GuardSettings.from_config(self.config)
        self.engine = GuardEngine(self.settings)
        self.plugin_data_dir = Path(get_astrbot_data_path()) / "plugin_data" / self.name
        self.audit_dir = self.plugin_data_dir / "audit"
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge_base = GuardKnowledgeBase(self.plugin_data_dir)
        self.runtime = GuardRuntime(self.knowledge_base)
        self.llm_client = GuardLLMClient(self.context, self.settings)
        self._evolve_job_id: str | None = None

    async def initialize(self) -> None:
        if self.settings.auto_seed_knowledge:
            self.knowledge_base.ensure_seed_notes()
            self._guard_log("初始Guardrail知识库已生效")
        if self.settings.evolve_cron_enabled:
            await self._ensure_evolve_job()
        self._guard_log("插件已初始化")

    async def terminate(self) -> None:
        self._guard_log("插件已终止")

    @filter.command_group("guard")
    def guard(self) -> None:
        pass

    @guard.command("status")
    async def guard_status(self, event: AstrMessageEvent):
        """查看当前护栏运行状态。"""
        yield event.plain_result(self.engine.describe_runtime_status())

    @guard.command("kb")
    async def guard_kb(self, event: AstrMessageEvent):
        """查看当前知识库摘要。"""
        summary = self.knowledge_base.summarize_for_prompt(limit=5) or "知识库当前为空。"
        yield event.plain_result(summary)

    @guard.command("provider")
    async def guard_provider(self, event: AstrMessageEvent):
        """查看当前插件内部使用的 LLM 配置。"""
        if self.settings.llm_mode == "openai_compatible_api":
            text = (
                f"llm_mode=openai_compatible_api, "
                f"base_url={self.settings.openai_base_url}, "
                f"model={self.settings.openai_model}"
            )
        else:
            provider_id = self.settings.astrbot_provider_id or "(follow current session provider)"
            text = f"llm_mode=astrbot_provider, provider_id={provider_id}"
        yield event.plain_result(text)

    @guard.command("note")
    async def guard_note(self, event: AstrMessageEvent, title: str, content: str):
        """写入一条手工维护的知识库笔记。"""
        path = self.knowledge_base.append_note(
            title=title,
            category="manual",
            summary=content[:160],
            content=content,
            source="manual_command",
        )
        yield event.plain_result(f"知识库笔记已写入: {path.name}")

    @guard.command("evolve")
    async def guard_evolve(self, event: AstrMessageEvent):
        """手动触发一次知识库演化。"""
        count = await self._run_evolution_cycle()
        yield event.plain_result(f"本次共处理 {count} 条待演化记录。")

    @guard.command("scan")
    async def guard_scan(self, event: AstrMessageEvent, text: str):
        """测试输入护栏。"""
        decision = await self.engine.evaluate_input(text, self.llm_client)
        yield event.plain_result(self.engine.render_decision("input", decision))

    @guard.command("review")
    async def guard_review(self, event: AstrMessageEvent, text: str):
        """测试输出护栏。"""
        decision = await self.engine.evaluate_output(text, self.llm_client)
        yield event.plain_result(self.engine.render_decision("output", decision))

    @guard.command("safe")
    async def guard_safe(self, event: AstrMessageEvent, prompt: str):
        """手动调用远程 SafeDecoding 服务。"""
        if not self.settings.safe_decoding_enabled:
            yield event.plain_result("SafeDecoding 未启用，请先在插件配置中打开远程 SafeDecoding 服务接入。")
            return

        try:
            content = await self.engine.safe_decode(prompt)
        except Exception as exc:
            logger.warning("safe decoding failed: %s", exc)
            yield event.plain_result(f"SafeDecoding 调用失败: {exc}")
            return

        yield event.plain_result(content)

    @filter.on_agent_begin(priority=100)
    async def on_agent_begin(
        self,
        event: AstrMessageEvent,
        run_context: ContextWrapper[AstrAgentContext],
    ) -> None:
        if not self.settings.enabled:
            return
        self._guard_log(
            f"Guardrail 工具链已接入当前 Agent 会话 | tool_timeout={run_context.tool_call_timeout}",
            event,
        )

    @filter.on_llm_request(priority=100)
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        if not self.settings.enabled or not self.settings.input_guard_enabled:
            return

        if self.settings.dynamic_context_enabled:
            guard_context = self.runtime.build_dynamic_guard_context(event.unified_msg_origin)
            if guard_context:
                req.extra_user_content_parts = req.extra_user_content_parts or []
                req.extra_user_content_parts.append(TextPart(text=guard_context).mark_as_temp())
                self._guard_log("安全提示与摘要已加入知识库", event)

        prompt = (req.prompt or "").strip()
        if not prompt:
            return

        self._guard_log("输入护栏正在工作中", event)
        self._log_payload("原始输入", prompt)

        try:
            decision = await self.engine.evaluate_input(prompt, self.llm_client)
        except Exception as exc:
            logger.warning("input guard failed: %s", exc)
            return

        await self._persist_audit("input", prompt, decision)
        self._append_raw_event(
            event=event,
            phase="input",
            payload={"text": prompt},
            decision=decision,
        )

        if decision.action is GuardAction.BLOCK:
            self.runtime.update_session_profile(
                session_id=event.unified_msg_origin,
                risk_score=decision.score,
                input_blocked=True,
            )
            self._guard_log(
                f"输入护栏已阻断请求 | score={decision.score:.2f} | reasons={decision.reasons}",
                event,
            )
            event.set_result(event.plain_result(self.engine.block_message("input", decision)))
            event.stop_event()
            event.should_call_llm(False)
            return

        if decision.action is GuardAction.REWRITE and decision.rewritten_text:
            self.runtime.update_session_profile(
                session_id=event.unified_msg_origin,
                risk_score=decision.score,
                input_rewritten=True,
            )
            req.prompt = decision.rewritten_text
            self._log_payload("优化后的输入", decision.rewritten_text)
        else:
            self.runtime.update_session_profile(
                session_id=event.unified_msg_origin,
                risk_score=decision.score,
            )

        self._wrap_request_tools(req, event)

        self._guard_log(
            f"输入护栏处理完成 | action={decision.action.value} | score={decision.score:.2f}",
            event,
        )

    @filter.on_llm_response(priority=100)
    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse) -> None:
        if not self.settings.enabled or not self.settings.output_guard_enabled:
            return

        content = (resp.completion_text or "").strip()
        if not content:
            return

        self._guard_log("输出护栏正在工作中", event)
        self._log_payload("原始输出", content)

        try:
            decision = await self.engine.evaluate_output(content, self.llm_client)
        except Exception as exc:
            logger.warning("output guard failed: %s", exc)
            return

        await self._persist_audit("output", content, decision)
        self._append_raw_event(
            event=event,
            phase="output",
            payload={"text": content},
            decision=decision,
        )

        if decision.action is GuardAction.BLOCK:
            self.runtime.update_session_profile(
                session_id=event.unified_msg_origin,
                risk_score=decision.score,
                output_blocked=True,
            )
            resp.completion_text = self.engine.block_message("output", decision)
            self._guard_log(
                f"输出护栏已阻断返回内容 | score={decision.score:.2f} | reasons={decision.reasons}",
                event,
            )
            return

        if decision.action is GuardAction.REWRITE and decision.rewritten_text:
            self.runtime.update_session_profile(
                session_id=event.unified_msg_origin,
                risk_score=decision.score,
                output_rewritten=True,
            )
            resp.completion_text = decision.rewritten_text
            self._log_payload("优化后的输出", decision.rewritten_text)
        else:
            self.runtime.update_session_profile(
                session_id=event.unified_msg_origin,
                risk_score=decision.score,
            )

        if self.settings.auto_collect_dialogue:
            self.runtime.append_dialogue_note(
                session_id=event.unified_msg_origin,
                user_text=event.message_str or "",
                model_text=resp.completion_text or "",
                risk_summary=self.engine.render_decision("output", decision),
            )
            self._guard_log("安全提示与摘要已加入知识库", event)

        self._guard_log(
            f"输出护栏处理完成 | action={decision.action.value} | score={decision.score:.2f}",
            event,
        )

    async def _persist_audit(self, phase: str, original_text: str, decision: GuardDecision) -> None:
        if not self.settings.write_audit_log:
            return

        try:
            content = build_audit_markdown(phase, original_text, decision)
            target = self.audit_dir / f"{phase}_{decision.audit_id}.md"
            target.write_text(content, encoding="utf-8")
        except Exception as exc:
            logger.warning("failed to persist audit log: %s", exc)

    def _append_raw_event(
        self,
        *,
        event: AstrMessageEvent,
        phase: str,
        payload: dict[str, Any],
        decision: GuardDecision,
    ) -> None:
        raw_payload = {
            "phase": phase,
            "session_id": event.unified_msg_origin,
            "sender": event.get_sender_name(),
            "decision": {
                "action": decision.action.value,
                "score": decision.score,
                "reasons": decision.reasons,
                "hits": decision.hits,
            },
        }
        raw_payload.update(payload)
        self.knowledge_base.append_raw_event(raw_payload)

    async def _ensure_evolve_job(self) -> None:
        cron_mgr = self.context.cron_manager
        if self._evolve_job_id:
            return
        job = await cron_mgr.add_basic_job(
            name=f"{self.name}_evolve",
            cron_expression=self.settings.evolve_cron_expression,
            handler=self._run_evolution_cycle,
            description="Periodically aggregate runtime guard records into markdown knowledge notes.",
            persistent=False,
        )
        self._evolve_job_id = job.job_id

    async def _run_evolution_cycle(self) -> int:
        count = 0
        for raw_path in sorted(self.knowledge_base.raw_dir.glob("*.json"))[:20]:
            try:
                payload = raw_path.read_text(encoding="utf-8")
            except Exception:
                continue
            note = await self._build_evolution_note(raw_path.stem, payload)
            self.knowledge_base.append_note(
                title=note["title"],
                category=note["category"],
                summary=note["summary"],
                content=note["content"],
                source=note["source"],
            )
            try:
                raw_path.unlink()
            except Exception:
                pass
            count += 1
        if count:
            self._guard_log(f"演化周期完成 | new_notes={count}")
        return count

    async def _build_evolution_note(self, stem: str, payload: str) -> dict[str, str]:
        system_prompt = (
            "You are generating a compact markdown-knowledge note for an LLM safety guard plugin. "
            "Return a JSON object with keys: title, category, summary, content, source."
        )
        prompt = (
            "Please transform the following runtime guard event into a reusable knowledge note.\n"
            "Requirements:\n"
            "1. title should be short and filesystem-safe.\n"
            "2. category should be one of defense, jailbreak, output_safety, evolution, profile, dialogue_memory, tool_guard.\n"
            "3. summary should be <= 200 chars.\n"
            "4. content should explain what happened, what rule was triggered and what future guard improvement it suggests.\n"
            f"Runtime event:\n{payload}"
        )
        try:
            result = await self.llm_client.complete_json(
                prompt=prompt,
                system_prompt=system_prompt,
                umo="guard:evolution",
            )
            return {
                "title": str(result.get("title", f"evolve_{stem}")),
                "category": str(result.get("category", "evolution")),
                "summary": str(result.get("summary", "Runtime guard event aggregated into knowledge base.")),
                "content": str(result.get("content", payload)),
                "source": str(result.get("source", "evolution_cycle")),
            }
        except Exception as exc:
            logger.warning("LLM evolution note build failed, fallback to raw payload: %s", exc)
            return {
                "title": f"evolve_{stem}",
                "category": "evolution",
                "summary": "Runtime guard event aggregated into knowledge base.",
                "content": payload,
                "source": "evolution_cycle_fallback",
            }

    def _guard_log(self, message: str, event: AstrMessageEvent | None = None) -> None:
        if not self.settings.log_guard_progress:
            return
        session = f" | session={event.unified_msg_origin}" if event else ""
        logger.info("[%s] %s%s", self.name, message, session)

    def _log_payload(self, label: str, content: str) -> None:
        if not self.settings.log_rewritten_payload:
            return
        compact = " ".join(content.split())
        preview = compact[:800]
        if len(compact) > 800:
            preview += "...<truncated>"
        logger.info("[%s] %s: %s", self.name, label, preview)

    def _serialize_tool_args(self, tool_name: str, tool_args: dict | None) -> str:
        payload = {"tool_name": tool_name, "tool_args": tool_args or {}}
        try:
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(payload)

    def _wrap_request_tools(self, req: ProviderRequest, event: AstrMessageEvent) -> None:
        if not self.settings.tool_input_guard_enabled and not self.settings.tool_output_guard_enabled:
            return
        if getattr(req, "_guard_toolset_wrapped", False):
            return
        if not req.func_tool:
            return

        req.func_tool = wrap_toolset(self, req.func_tool)
        setattr(req, "_guard_toolset_wrapped", True)
        self._guard_log("Guardrail 工具代理已注入当前请求工具链", event)

    def _rewrite_tool_args(self, tool_args: dict[str, Any], decision: GuardDecision) -> None:
        preferred_keys = ("input", "query", "prompt", "text", "content", "command")
        for key in preferred_keys:
            value = tool_args.get(key)
            if isinstance(value, str) and decision.rewritten_text:
                tool_args[key] = decision.rewritten_text
                return

        for key, value in list(tool_args.items()):
            tool_args[key] = self._sanitize_value(value, decision.hits)

    def _sanitize_value(self, value: Any, hits: list[str]) -> Any:
        if isinstance(value, str):
            return self.engine.sanitize_text(value, hits)
        if isinstance(value, list):
            return [self._sanitize_value(item, hits) for item in value]
        if isinstance(value, dict):
            return {key: self._sanitize_value(item, hits) for key, item in value.items()}
        return value
