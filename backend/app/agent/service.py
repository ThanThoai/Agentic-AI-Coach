from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import structlog

from app.core.config import Settings
from app.core.config import settings as _settings
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
        self._llm_timeout = cfg.agent_llm_timeout
        self._tool_timeout = cfg.agent_tool_timeout

    async def _llm_call(self, messages: list[dict[str, Any]]) -> AgentLLMResponse:
        return await asyncio.wait_for(
            self._provider.complete_with_tools(
                messages=messages,
                tools=TOOL_SCHEMAS,
                model=self._model,
                max_tokens=1024,
                temperature=0.3,
                system=COACH_AGENT_SYSTEM,
            ),
            timeout=self._llm_timeout,
        )

    async def _tool_call(self, tool_calls: list[ToolCall]) -> list[tuple[str, str]]:
        return await asyncio.wait_for(
            execute_tools(tool_calls),
            timeout=self._tool_timeout,
        )

    async def _run_with_keepalive(
        self,
        coro,
        timeout: float,
        ping_interval: float = 5.0,
    ):
        """Run *coro* and yield {"type":"ping"} every *ping_interval* seconds.

        Raises TimeoutError if *coro* does not complete within *timeout*.
        Designed to be used with 'async for' in run_stream so SSE connections
        don't time out during long-running LLM or tool calls.
        """
        task = asyncio.create_task(asyncio.wait_for(coro, timeout=timeout))
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=ping_interval)
                if done:
                    break
                yield {"type": "ping"}
            yield task.result()
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
            raise TimeoutError from None

    async def run(self, question: str, user_id: uuid.UUID) -> dict[str, Any]:
        """Run the agent loop and return a dict with answer, tools_used, usage."""
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        tools_used: list[str] = []
        total_usage = TokenUsage()

        for iteration in range(self._max_iterations):
            try:
                response: AgentLLMResponse = await self._llm_call(messages)
            except TimeoutError:
                log.error(
                    "agent.llm.timeout",
                    iteration=iteration + 1,
                    timeout_s=self._llm_timeout,
                    user_id=str(user_id),
                )
                raise AgentError("llm_timeout")

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
                try:
                    results = await self._tool_call(tool_calls)
                except TimeoutError:
                    tool_names = [tc.name for tc in tool_calls]
                    log.error(
                        "agent.tools.timeout",
                        tools=tool_names,
                        timeout_s=self._tool_timeout,
                        user_id=str(user_id),
                    )
                    raise AgentError("tool_timeout")
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

    async def run_stream(
        self, question: str, user_id: uuid.UUID
    ) -> AsyncGenerator[dict[str, Any], None]:
        """ReAct loop with SSE events.

        Yields:
          {"type": "status", "tools": ["rag_search", ...]}  — before each tool batch
          {"type": "token",  "content": "..."}              — chars of the final answer
          {"type": "done",   "answer": ..., ...}            — after all tokens
        """
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        tools_used: list[str] = []
        total_usage = TokenUsage()

        for iteration in range(self._max_iterations):
            # ── LLM call (with keepalive so SSE stays alive) ──────────────────
            response: AgentLLMResponse | None = None
            try:
                async for _event in self._run_with_keepalive(
                    self._provider.complete_with_tools(
                        messages=messages,
                        tools=TOOL_SCHEMAS,
                        model=self._model,
                        max_tokens=1024,
                        temperature=0.3,
                        system=COACH_AGENT_SYSTEM,
                    ),
                    timeout=self._llm_timeout,
                ):
                    if isinstance(_event, dict):
                        yield _event          # forward ping to client
                    else:
                        response = _event     # AgentLLMResponse result
            except TimeoutError:
                log.error(
                    "agent.llm.timeout",
                    iteration=iteration + 1,
                    timeout_s=self._llm_timeout,
                    user_id=str(user_id),
                )
                yield {
                    "type": "error",
                    "message": "The AI took too long to respond. Please try again.",
                }
                return

            assert response is not None
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
                if answer:
                    yield {"type": "token", "content": answer}
                else:
                    log.warning(
                        "agent.empty_answer",
                        iteration=iteration + 1,
                        user_id=str(user_id),
                    )
                yield {
                    "type": "done",
                    "answer": answer,
                    "tools_used": tools_used,
                    "iterations": iteration + 1,
                    "usage": total_usage.model_dump(),
                }
                return

            if response.stop_reason == "tool_use":
                tool_calls = _extract_tool_calls(response.content_blocks)
                tool_names = [tc.name for tc in tool_calls]

                yield {"type": "status", "tools": tool_names}

                # ── Tool execution (with keepalive) ───────────────────────────
                results: list[tuple[str, str]] | None = None
                try:
                    async for _event in self._run_with_keepalive(
                        execute_tools(tool_calls),
                        timeout=self._tool_timeout,
                    ):
                        if isinstance(_event, dict):
                            yield _event      # forward ping to client
                        else:
                            results = _event  # list[tuple[str, str]]
                except TimeoutError:
                    log.error(
                        "agent.tools.timeout",
                        tools=tool_names,
                        timeout_s=self._tool_timeout,
                        user_id=str(user_id),
                    )
                    yield {
                        "type": "error",
                        "message": "A tool took too long to respond. Please try again.",
                    }
                    return

                assert results is not None
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

        yield {
            "type": "error",
            "message": "Agent could not produce an answer within the iteration limit.",
        }
