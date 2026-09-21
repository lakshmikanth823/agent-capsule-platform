"""
Software Capsule Platform - Control Plane API
"""
from fastapi import FastAPI

app = FastAPI(
    title="Software Capsule Platform Control Plane",
    version="0.1.0",
    description="Authoritative control plane for Software Capsules",
)

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "control-plane", "version": "0.1.0"}
