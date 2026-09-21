"""
API router package.
"""
from fastapi import APIRouter
from .apps import router as apps_router
from .tokens import router as tokens_router
from .artifacts import router as artifacts_router
from .audit import router as audit_router

api_router = APIRouter()
api_router.include_router(apps_router)
api_router.include_router(tokens_router)
api_router.include_router(artifacts_router)
api_router.include_router(audit_router)

__all__ = ["api_router"]
