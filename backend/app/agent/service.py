from __future__ import annotations

import uuid
from typing import Any

import structlog

from app.core.config import Settings, settings as _settings
from app.llm.base import AgentLLMResponse, ContentBlock, TokenUsage, ToolCall
from app.llm.factory import get_step_provider

from .prompts import COACH_AGENT_SYSTEM
from .tool_schemas import TOOL_SCHEMAS
from .tools import execute_tools

log = structlog.get_logger(__name__)


class AgentError(Exception):
    pass


def _extract_text(blocks: list[ContentBlock]) -> str:
    return " ".join(b.text for b in blocks if b.type == "text" and b.text)


def _extract_tool_calls(blocks: list[ContentBlock]) -> list[ToolCall]:
    return [b.tool_call for b in blocks if b.type == "tool_use" and b.tool_call is not None]


def _assistant_turn_raw(blocks: list[ContentBlock]) -> list[dict[str, Any]]:
    """Convert ContentBlock list to Anthropic-format raw dicts for the messages array."""
    raw: list[dict[str, Any]] = []
    for b in blocks:
        if b.type == "text" and b.text:
            raw.append({"type": "text", "text": b.text})
        elif b.type == "tool_use" and b.tool_call:
            raw.append(
                {
                    "type": "tool_use",
                    "id": b.tool_call.id,
                    "name": b.tool_call.name,
                    "input": b.tool_call.input,
                }
            )
    return raw


class AgentService:
    def __init__(self, cfg: Settings = _settings) -> None:
        self._provider = get_step_provider(cfg.agent_provider, cfg)
        self._model = cfg.agent_model
        self._max_iterations = cfg.agent_max_iterations

    async def run(self, question: str, user_id: uuid.UUID) -> dict[str, Any]:
        """Run the agent loop and return a dict with answer, tools_used, usage."""
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        tools_used: list[str] = []
        total_usage = TokenUsage()

        for iteration in range(self._max_iterations):
            response: AgentLLMResponse = await self._provider.complete_with_tools(
                messages=messages,
                tools=TOOL_SCHEMAS,
                model=self._model,
                max_tokens=1024,
                temperature=0.3,
                system=COACH_AGENT_SYSTEM,
            )

            total_usage += response.usage

            messages.append(
                {"role": "assistant", "content": _assistant_turn_raw(response.content_blocks)}
            )

            log.info(
                "agent.iteration",
                iteration=iteration + 1,
                stop_reason=response.stop_reason,
                user_id=str(user_id),
            )

            if response.stop_reason in ("end_turn", "max_tokens"):
                answer = _extract_text(response.content_blocks)
                return {
                    "answer": answer,
                    "tools_used": tools_used,
                    "iterations": iteration + 1,
                    "usage": total_usage,
                }

            if response.stop_reason == "tool_use":
                tool_calls = _extract_tool_calls(response.content_blocks)
                results = await execute_tools(tool_calls)
                tools_used.extend(name for name, _ in results)

                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tc.id,
                                "content": result,
                            }
                            for tc, (_, result) in zip(tool_calls, results)
                        ],
                    }
                )

        raise AgentError("max_iterations_exceeded")
