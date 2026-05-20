from __future__ import annotations

import copy
from typing import Any

import mcp.types
from mcp.types import CallToolResult, EmbeddedResource, TextContent, TextResourceContents

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor

from .engine import GuardAction


class GuardedFunctionTool(FunctionTool[AstrAgentContext]):
    def __init__(self, plugin: Any, original_tool: FunctionTool[AstrAgentContext]) -> None:
        super().__init__(
            name=original_tool.name,
            parameters=copy.deepcopy(original_tool.parameters),
            description=original_tool.description,
        )
        self.plugin = plugin
        self.original_tool = original_tool
        self.active = getattr(original_tool, "active", True)
        self.is_background_task = getattr(original_tool, "is_background_task", False)
        self.handler_module_path = getattr(original_tool, "handler_module_path", None)

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs,
    ) -> CallToolResult:
        event = context.context.event
        tool_name = self.name
        serialized = self.plugin._serialize_tool_args(tool_name, kwargs)

        self.plugin._guard_log(f"工具调用输入护栏正在工作中 | tool={tool_name}", event)
        self.plugin._log_payload("工具调用原始输入", serialized)

        input_decision = await self.plugin.engine.evaluate_input(serialized, self.plugin.llm_client)
        await self.plugin._persist_audit("tool_input", serialized, input_decision)
        self.plugin._append_raw_event(
            event=event,
            phase="tool_input",
            payload={
                "tool_name": tool_name,
                "tool_args": kwargs,
            },
            decision=input_decision,
        )

        if input_decision.action is GuardAction.BLOCK:
            blocked_text = (
                f"Tool `{tool_name}` blocked by guardrail. "
                f"{self.plugin.engine.block_message('tool_input', input_decision)}"
            )
            self.plugin._guard_log(
                f"已阻断工具调用 | tool={tool_name} | score={input_decision.score:.2f}",
                event,
            )
            return self._text_result(blocked_text)

        delegated_kwargs = copy.deepcopy(kwargs)
        if input_decision.action is GuardAction.REWRITE and input_decision.rewritten_text:
            self.plugin._rewrite_tool_args(delegated_kwargs, input_decision)
            self.plugin._log_payload(
                "工具调用优化后输入",
                self.plugin._serialize_tool_args(tool_name, delegated_kwargs),
            )

        input_summary = (
            f"工具输入护栏处理完成 | tool={tool_name} | "
            f"action={input_decision.action.value} | score={input_decision.score:.2f}"
        )
        self.plugin._guard_log(input_summary, event)

        tool_result = await self._delegate_call(context, delegated_kwargs)
        tool_text = self._result_to_text(tool_result)
        if not tool_text:
            return tool_result

        self.plugin._guard_log(f"工具调用输出护栏正在工作中 | tool={tool_name}", event)
        self.plugin._log_payload("工具调用原始输出", tool_text)

        output_decision = await self.plugin.engine.evaluate_output(tool_text, self.plugin.llm_client)
        await self.plugin._persist_audit("tool_output", tool_text, output_decision)
        self.plugin._append_raw_event(
            event=event,
            phase="tool_output",
            payload={
                "tool_name": tool_name,
                "tool_args": delegated_kwargs,
                "tool_result": tool_text,
            },
            decision=output_decision,
        )

        if output_decision.action is GuardAction.BLOCK:
            blocked_text = (
                f"Tool `{tool_name}` result blocked by guardrail. "
                f"{self.plugin.engine.block_message('tool_output', output_decision)}"
            )
            self.plugin._guard_log(
                f"工具输出已阻断 | tool={tool_name} | score={output_decision.score:.2f}",
                event,
            )
            return self._text_result(blocked_text)

        if output_decision.action is GuardAction.REWRITE and output_decision.rewritten_text:
            self.plugin._log_payload("工具调用优化后输出", output_decision.rewritten_text)
            self.plugin._guard_log(
                f"工具输出护栏处理完成 | tool={tool_name} | action={output_decision.action.value} | score={output_decision.score:.2f}",
                event,
            )
            return self._text_result(output_decision.rewritten_text)

        self.plugin._guard_log(
            f"工具输出护栏处理完成 | tool={tool_name} | action={output_decision.action.value} | score={output_decision.score:.2f}",
            event,
        )
        return tool_result

    async def _delegate_call(
        self,
        context: ContextWrapper[AstrAgentContext],
        kwargs: dict[str, Any],
    ) -> CallToolResult:
        executor = FunctionToolExecutor.execute(
            tool=self.original_tool,
            run_context=context,
            **kwargs,
        )
        aggregated_content: list[Any] = []
        has_none_result = False

        async for resp in executor:
            if isinstance(resp, CallToolResult):
                aggregated_content.extend(resp.content or [])
            elif resp is None:
                has_none_result = True
            else:
                aggregated_content.append(TextContent(type="text", text=str(resp)))

        if aggregated_content:
            return CallToolResult(content=aggregated_content)
        if has_none_result:
            return self._text_result("The tool has no return value, or has sent the result directly to the user.")
        return self._text_result("The tool returned no content.")

    def _result_to_text(self, tool_result: CallToolResult) -> str:
        if not tool_result.content:
            return ""

        parts: list[str] = []
        for item in tool_result.content:
            if isinstance(item, TextContent):
                parts.append(item.text)
            elif isinstance(item, EmbeddedResource) and isinstance(item.resource, TextResourceContents):
                parts.append(item.resource.text)
            else:
                parts.append(str(item))
        return "\n\n".join(part for part in parts if part).strip()

    def _text_result(self, text: str) -> CallToolResult:
        return CallToolResult(content=[TextContent(type="text", text=text)])


def wrap_toolset(plugin: Any, toolset: ToolSet | None) -> ToolSet | None:
    if toolset is None:
        return None

    wrapped = ToolSet()
    for tool in toolset:
        if isinstance(tool, GuardedFunctionTool):
            wrapped.add_tool(tool)
        else:
            wrapped.add_tool(GuardedFunctionTool(plugin, tool))
    return wrapped
