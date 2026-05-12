from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, rag, workout

router = APIRouter()
router.include_router(auth.router)
router.include_router(rag.router)
router.include_router(workout.router)
