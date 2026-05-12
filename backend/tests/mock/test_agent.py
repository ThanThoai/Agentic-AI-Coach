"""
Mock tests for Feature 3 — Coach Assist Agent.
All LLM calls are intercepted; no real API keys or database needed.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.service import AgentService
from app.agent.tools import dispatch_tool, execute_tools
from app.llm.base import (
    AgentLLMResponse,
    ContentBlock,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)
from app.schemas.agent import AgentRequest, AgentResponse


# ── Helpers ───────────────────────────────────────────────────────────────────

def _text_response(text: str = "Here is your coaching advice.") -> AgentLLMResponse:
    return AgentLLMResponse(
        stop_reason="end_turn",
        content_blocks=[ContentBlock(type="text", text=text)],
        model="mock",
        provider="mock",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )


def _tool_response(tool_name: str, tool_id: str = "tu_01", **inputs) -> AgentLLMResponse:
    return AgentLLMResponse(
        stop_reason="tool_use",
        content_blocks=[
            ContentBlock(
                type="tool_use",
                tool_call=ToolCall(id=tool_id, name=tool_name, input=inputs),
            )
        ],
        model="mock",
        provider="mock",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )


USER_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


# ── AgentLLMResponse model ────────────────────────────────────────────────────

def test_agent_llm_response_end_turn():
    resp = _text_response("Great progress!")
    assert resp.stop_reason == "end_turn"
    assert resp.content_blocks[0].text == "Great progress!"


def test_agent_llm_response_tool_use():
    resp = _tool_response("rag_search", query="progressive overload")
    assert resp.stop_reason == "tool_use"
    tc = resp.content_blocks[0].tool_call
    assert tc is not None
    assert tc.name == "rag_search"
    assert tc.input == {"query": "progressive overload"}


# ── Token usage accumulation ──────────────────────────────────────────────────

def test_token_usage_iadd():
    a = TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    b = TokenUsage(prompt_tokens=5, completion_tokens=8, total_tokens=13)
    a += b
    assert a.prompt_tokens == 15
    assert a.completion_tokens == 28
    assert a.total_tokens == 43


# ── dispatch_tool ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_unknown_tool():
    tc = ToolCall(id="x", name="nonexistent_tool", input={})
    result = await dispatch_tool(tc)
    assert "ERROR" in result
    assert "Unknown tool" in result


@pytest.mark.asyncio
async def test_dispatch_rag_search():
    tc = ToolCall(id="x", name="rag_search", input={"query": "progressive overload"})
    mock_fn = AsyncMock(return_value="=== KNOWLEDGE BASE ===\n[1] test.md\n    Some text")
    with patch("app.agent.tools.TOOL_REGISTRY", {"rag_search": mock_fn, "analyze_history": AsyncMock()}):
        result = await dispatch_tool(tc)
    assert "KNOWLEDGE BASE" in result


@pytest.mark.asyncio
async def test_dispatch_analyze_history():
    tc = ToolCall(id="x", name="analyze_history", input={"athlete": "Alex", "question": "bench press trend"})
    mock_fn = AsyncMock(return_value="=== WORKOUT ANALYSIS ===\nBench: 80→90 kg")
    with patch("app.agent.tools.TOOL_REGISTRY", {"rag_search": AsyncMock(), "analyze_history": mock_fn}):
        result = await dispatch_tool(tc)
    assert "WORKOUT ANALYSIS" in result


@pytest.mark.asyncio
async def test_dispatch_tool_exception_returns_error_string():
    tc = ToolCall(id="x", name="rag_search", input={"query": "test"})
    mock_fn = AsyncMock(side_effect=RuntimeError("qdrant down"))
    with patch("app.agent.tools.TOOL_REGISTRY", {"rag_search": mock_fn, "analyze_history": AsyncMock()}):
        result = await dispatch_tool(tc)
    assert "ERROR" in result
    assert "qdrant down" in result


# ── execute_tools ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_tools_parallel():
    calls = [
        ToolCall(id="t1", name="rag_search", input={"query": "overload"}),
        ToolCall(id="t2", name="analyze_history", input={"athlete": "Alex", "question": "bench trend"}),
    ]
    rag_result = "=== KNOWLEDGE BASE ===\n[1] test.md\n    overload info"
    analysis_result = "=== WORKOUT ANALYSIS ===\nbench 80→90"

    with patch(
        "app.agent.tools.TOOL_REGISTRY",
        {
            "rag_search": AsyncMock(return_value=rag_result),
            "analyze_history": AsyncMock(return_value=analysis_result),
        },
    ):
        results = await execute_tools(calls)

    assert len(results) == 2
    names = [name for name, _ in results]
    assert "rag_search" in names
    assert "analyze_history" in names


# ── AgentService ──────────────────────────────────────────────────────────────

class MockAgentProvider:
    """Simulates an LLM that calls one tool then returns a text answer."""

    def __init__(self, responses: list[AgentLLMResponse]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    async def complete_with_tools(self, messages, tools, **kwargs) -> AgentLLMResponse:
        resp = self._responses[self._call_count % len(self._responses)]
        self._call_count += 1
        return resp


@pytest.mark.asyncio
async def test_agent_service_end_turn_immediately():
    """Agent that answers on the first turn without calling any tools."""
    provider = MockAgentProvider([_text_response("No tools needed.")])
    service = AgentService.__new__(AgentService)
    service._provider = provider
    service._model = None
    service._max_iterations = 4

    result = await service.run("What is progressive overload?", USER_ID)
    assert result["answer"] == "No tools needed."
    assert result["tools_used"] == []
    assert result["iterations"] == 1


@pytest.mark.asyncio
async def test_agent_service_single_tool_then_answer():
    """Agent calls rag_search once then synthesises a final answer."""
    tool_resp = _tool_response("rag_search", "tu_01", query="progressive overload")
    final_resp = _text_response("Here is the coaching answer.")

    provider = MockAgentProvider([tool_resp, final_resp])
    service = AgentService.__new__(AgentService)
    service._provider = provider
    service._model = None
    service._max_iterations = 4

    rag_result = "=== KNOWLEDGE BASE ===\n[1] test.md\n    overload text"
    with patch("app.agent.tools.tool_rag_search", new=AsyncMock(return_value=rag_result)):
        result = await service.run("What is progressive overload?", USER_ID)

    assert result["answer"] == "Here is the coaching answer."
    assert "rag_search" in result["tools_used"]
    assert result["iterations"] == 2


@pytest.mark.asyncio
async def test_agent_service_parallel_tools_then_answer():
    """Agent calls both tools in a single turn then synthesises."""
    parallel_resp = AgentLLMResponse(
        stop_reason="tool_use",
        content_blocks=[
            ContentBlock(
                type="tool_use",
                tool_call=ToolCall(id="t1", name="analyze_history", input={"question": "bench trend"}),
            ),
            ContentBlock(
                type="tool_use",
                tool_call=ToolCall(id="t2", name="rag_search", input={"query": "progressive overload"}),
            ),
        ],
        model="mock",
        provider="mock",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )
    final_resp = _text_response("Grounded coaching answer.")

    provider = MockAgentProvider([parallel_resp, final_resp])
    service = AgentService.__new__(AgentService)
    service._provider = provider
    service._model = None
    service._max_iterations = 4

    with (
        patch("app.agent.tools.tool_analyze_history", new=AsyncMock(return_value="=== WORKOUT ANALYSIS ===")),
        patch("app.agent.tools.tool_rag_search", new=AsyncMock(return_value="=== KNOWLEDGE BASE ===")),
    ):
        result = await service.run("Is my bench ready to go heavier?", USER_ID)

    assert result["answer"] == "Grounded coaching answer."
    assert set(result["tools_used"]) == {"analyze_history", "rag_search"}
    assert result["iterations"] == 2


@pytest.mark.asyncio
async def test_agent_service_max_iterations_exceeded():
    """Agent that keeps calling tools should raise AgentError after MAX_ITERATIONS."""
    from app.agent.service import AgentError

    always_tool = _tool_response("rag_search", "tu_loop", query="loop")
    provider = MockAgentProvider([always_tool])
    service = AgentService.__new__(AgentService)
    service._provider = provider
    service._model = None
    service._max_iterations = 2  # force fast exhaustion

    with patch("app.agent.tools.tool_rag_search", new=AsyncMock(return_value="=== KB ===")):
        with pytest.raises(AgentError, match="max_iterations_exceeded"):
            await service.run("Loop forever", USER_ID)


# ── API schema validation ─────────────────────────────────────────────────────

def test_agent_request_min_length():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentRequest(question="Hi")  # too short (< 5)


def test_agent_request_valid():
    req = AgentRequest(question="What is my bench press trend?")
    assert req.question == "What is my bench press trend?"


def test_agent_response_shape():
    resp = AgentResponse(
        answer="Your bench is strong.",
        tools_used=["analyze_history", "rag_search"],
        iterations=2,
        usage=TokenUsage(prompt_tokens=50, completion_tokens=100, total_tokens=150),
    )
    assert resp.iterations == 2
    assert "analyze_history" in resp.tools_used
