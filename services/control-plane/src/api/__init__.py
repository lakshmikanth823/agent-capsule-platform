"""
API router package.
"""
from fastapi import APIRouter
from .apps import router as apps_router
from .shares import router as shares_router
from .tokens import router as tokens_router
from .artifacts import router as artifacts_router
from .audit import router as audit_router
from .auth import router as auth_router
from .connectors import router as connectors_router
from .kill_switch import router as kill_switch_router
from .profiles import router as profiles_router
from .domains import router as domains_router
from .sso import router as sso_router
from .scim import router as scim_router
from .group_mappings import router as group_mappings_router
from .governance import router as governance_router
from .ai import router as ai_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(apps_router)
api_router.include_router(shares_router)
api_router.include_router(tokens_router)
api_router.include_router(artifacts_router)
api_router.include_router(audit_router)
api_router.include_router(connectors_router)
api_router.include_router(kill_switch_router)
api_router.include_router(profiles_router)
api_router.include_router(domains_router)
api_router.include_router(sso_router)
api_router.include_router(scim_router)
api_router.include_router(group_mappings_router)
api_router.include_router(governance_router)
api_router.include_router(ai_router)

__all__ = ["api_router"]
