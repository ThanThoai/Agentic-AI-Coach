"""Agent pipeline runner for evaluation."""
from __future__ import annotations

import time
import uuid

from app.agent.roster import ATHLETE_ROSTER
from app.agent.service import AgentService
from app.core.config import settings
from app.schemas.agent import AgentResponse

from ..schemas import TestCase

# Use the first athlete's UUID as a stable coach user_id for evaluation
_EVAL_USER_ID = ATHLETE_ROSTER[0].user_id if ATHLETE_ROSTER else uuid.uuid4()


async def run_agent_case(
    case: TestCase,
    user_id: uuid.UUID | None = None,
) -> tuple[AgentResponse, int]:
    """Run the agent loop for one test case; return (response, latency_ms)."""
    service = AgentService(settings)
    uid = user_id or _EVAL_USER_ID

    t0 = time.monotonic()
    result = await service.run(case.question, user_id=uid)
    latency_ms = int((time.monotonic() - t0) * 1000)

    return AgentResponse(**result), latency_ms
