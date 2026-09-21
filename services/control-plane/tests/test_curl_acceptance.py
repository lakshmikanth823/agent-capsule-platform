"""
End-to-end acceptance test executing real curl commands against control-plane API.
Satisfies Acceptance: "I can create an app and publish a version with curl, and see the audit events."
"""
import os
import sys
import time
import uuid
import json
import socket
import subprocess
from pathlib import Path
import pytest

from storage import get_storage_driver


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def running_server():
    port = find_free_port()
    python_exe = sys.executable
    app_dir = str(Path(__file__).resolve().parent.parent / "src")

    # Start uvicorn server in background process
    proc = subprocess.Popen(
        [
            python_exe,
            "-m",
            "uvicorn",
            "--app-dir",
            app_dir,
            "main:app",
            "--port",
            str(port),
            "--host",
            "127.0.0.1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Wait for server to be responsive
    server_url = f"http://127.0.0.1:{port}"
    max_retries = 30
    for _ in range(max_retries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
        except Exception:
            pass
        time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("Uvicorn server failed to start within timeout.")

    yield server_url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.asyncio
async def test_curl_create_publish_and_audit(running_server):
    app_key = f"curl-app-{uuid.uuid4().hex[:8]}"
    storage = get_storage_driver()
    artifact_ref = f"artifacts/{app_key}.tar.gz"
    await storage.put(artifact_ref, b"curl test bundle content")

    manifest = {
        "apiVersion": "capsule/v1alpha1",
        "id": app_key,
        "name": "Curl Test App",
        "shape": "web-app",
        "runtime": "node22",
        "roles": ["admin", "viewer"],
        "capabilities": {
            "db": {
                "type": "sqlite",
            },
        },
        "egress": [],
        "sharing": {"default": "org"},
        "limits": {
            "cpu": "small",
            "memory_mb": 256,
            "request_timeout_s": 30,
        },
    }

    # 1. Create app with curl
    create_payload = json.dumps({
        "id": app_key,
        "name": "Curl Test App",
        "shape": "web-app",
        "runtime": "node22",
        "manifest": manifest,
    })

    cmd_create = [
        "curl.exe",
        "-s",
        "-X", "POST",
        f"{running_server}/v1/apps",
        "-H", "Authorization: Bearer mock-alice-token",
        "-H", "Content-Type: application/json",
        "-d", create_payload,
    ]
    res_create = subprocess.run(cmd_create, capture_output=True, text=True)
    assert res_create.returncode == 0
    app_data = json.loads(res_create.stdout)
    assert app_data["app_key"] == app_key
    app_id = app_data["id"]

    # 2. Publish version with curl
    publish_payload = json.dumps({
        "manifest": manifest,
        "artifact": {"ref": artifact_ref, "sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"},
        "change_description": "Published via curl",
    })

    cmd_publish = [
        "curl.exe",
        "-s",
        "-X", "POST",
        f"{running_server}/v1/apps/{app_id}/publish",
        "-H", "Authorization: Bearer mock-alice-token",
        "-H", "Content-Type: application/json",
        "-H", f"Idempotency-Key: curl-idempotency-key-{uuid.uuid4().hex}",
        "-d", publish_payload,
    ]
    res_publish = subprocess.run(cmd_publish, capture_output=True, text=True)
    assert res_publish.returncode == 0
    pub_data = json.loads(res_publish.stdout)
    assert pub_data["status"] == "succeeded"
    assert pub_data["app_id"] == app_id
    assert pub_data["version_id"] is not None

    # 3. Query audit events with curl
    cmd_audit = [
        "curl.exe",
        "-s",
        "-X", "GET",
        f"{running_server}/v1/audit/events?app_id={app_id}",
        "-H", "Authorization: Bearer mock-alice-token",
    ]
    res_audit = subprocess.run(cmd_audit, capture_output=True, text=True)
    assert res_audit.returncode == 0
    audit_events = json.loads(res_audit.stdout)
    assert isinstance(audit_events, list)
    actions = [e["action"] for e in audit_events]
    assert "app.create" in actions
    assert "app.publish" in actions
