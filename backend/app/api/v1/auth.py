"""Dev-only auth endpoint — returns signed demo JWTs for Alex and Binh.
Only available when app_env != production.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from jose import jwt
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

# Fixed stable UUIDs for demo users
DEMO_USERS: dict[str, tuple[uuid.UUID, str, str]] = {
    "alex":  (uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"), "Alex",  "athlete"),
    "binh":  (uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"), "Binh",  "athlete"),
    "coach": (uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"), "Coach", "coach"),
}


class DemoTokenResponse(BaseModel):
    user_id: str
    access_token: str
    token_type: str = "bearer"
    name: str
    role: str


@router.get(
    "/demo-token/{user_name}",
    response_model=DemoTokenResponse,
    summary="Get a demo JWT for dev/testing",
)
async def get_demo_token(user_name: str) -> DemoTokenResponse:
    """Returns a signed JWT for a named demo user. Production: always 404."""
    if settings.app_env == "production" and not settings.enable_demo_token:
        raise HTTPException(status_code=404)

    entry = DEMO_USERS.get(user_name.lower())
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown demo user: {user_name!r}")

    user_id, name, role = entry
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(days=7),
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return DemoTokenResponse(user_id=str(user_id), access_token=token, name=name, role=role)
