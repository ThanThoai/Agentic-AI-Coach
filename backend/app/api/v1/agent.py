from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from app.agent.service import AgentError, AgentService
from app.core.dependencies import get_current_role, get_current_user
from app.schemas.agent import AgentRequest, AgentResponse

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


def get_agent_service() -> AgentService:
    return AgentService()


@router.post(
    "/ask",
    response_model=AgentResponse,
    summary="Ask the coach assist agent a question",
    description=(
        "Runs the ReAct agent loop. Only accessible by users with role='coach'. "
        "Mention athlete names directly in the question (e.g. 'Alex', 'Binh') to "
        "target specific athletes. The agent resolves names server-side."
    ),
)
async def ask_agent(
    payload: AgentRequest,
    requester_id: uuid.UUID = Depends(get_current_user),
    role: str = Depends(get_current_role),
    service: AgentService = Depends(get_agent_service),
) -> AgentResponse:
    if role != "coach":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The agent endpoint is only available to coach accounts.",
        )

    try:
        result = await service.run(payload.question, requester_id)
    except AgentError as exc:
        log.error("agent.failed", user_id=str(requester_id), err=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent could not produce an answer. Please try again.",
        ) from exc

    return AgentResponse(
        answer=result["answer"],
        tools_used=result["tools_used"],
        iterations=result["iterations"],
        usage=result["usage"],
    )
