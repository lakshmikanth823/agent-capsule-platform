"""
Software Capsule Platform - Control Plane API
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from api import api_router

app = FastAPI(
    title="Software Capsule Platform Control Plane",
    version="0.1.0",
    description="Authoritative control plane for Software Capsules",
)

# CORS configuration: explicit origins required when allow_credentials=True
import os
cors_origins_env = os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:8080,http://127.0.0.1:8080,http://localhost:5173,http://127.0.0.1:5173",
)
allowed_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routes under /v1 and root
app.include_router(api_router, prefix="/v1")
app.include_router(api_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "control-plane", "version": "0.1.0"}
