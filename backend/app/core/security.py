from __future__ import annotations

import uuid
from datetime import datetime, timezone

from jose import JWTError, jwt

from app.core.config import settings


class AuthError(Exception):
    pass


def decode_access_token(token: str) -> uuid.UUID:
    """Decode a JWT and return the user_id (sub claim as UUID).
    Raises AuthError on any failure.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise AuthError("Invalid token") from exc

    sub = payload.get("sub")
    if sub is None:
        raise AuthError("Token missing sub claim")

    exp = payload.get("exp")
    if exp is not None and datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc):
        raise AuthError("Token expired")

    try:
        return uuid.UUID(str(sub))
    except ValueError as exc:
        raise AuthError("Token sub is not a valid UUID") from exc
