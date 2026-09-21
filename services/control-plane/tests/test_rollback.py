"""
Integration tests for Prompt 14: Versions, snapshots, and rollback.
Tests: deploy v1, v2 with new data, roll back code-only, roll back with data restore, undo the rollback.
Verify no data is lost silently.
"""
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from main import app as fastapi_app
from storage import get_storage_driver

MOCK_ALICE_TOKEN = "mock-alice-token"  # Owner
MOCK_BOB_TOKEN = "mock-bob-token"      # Regular User


@pytest.mark.asyncio
async def test_rollback_full_lifecycle():
    transport = ASGITransport(app=fastapi_app)
    app_key = f"rollback-{uuid.uuid4().hex[:8]}"
    storage = get_storage_driver()

    # Pre-seed artifacts in storage
    await storage.put(f"capsules/{app_key}/artifacts/v1.tar.gz", b"bundle v1")
    await storage.put(f"capsules/{app_key}/artifacts/v2.tar.gz", b"bundle v2")

    manifest_v1 = {
        "apiVersion": "capsule/v1alpha1",
        "id": app_key,
        "name": "Rollback Test App",
        "shape": "web-app",
        "runtime": "node22",
        "roles": ["employee"],
        "capabilities": {
            "db": {"type": "sqlite"},
            "identity": True,
        },
        "egress": [],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create App
        create_res = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "Rollback Test App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest_v1,
            },
        )
        assert create_res.status_code == 201, create_res.text
        app_data = create_res.json()
        app_id = app_data["id"]

        # Configure base data directory for test capsule
        base_data_dir = Path("data/capsules").resolve()
        capsule_db_dir = base_data_dir / app_id / "data"
        capsule_db_dir.mkdir(parents=True, exist_ok=True)
        live_db_file = capsule_db_dir / "app.sqlite"

        # 2. Deploy v1
        pub1_res = await client.post(
            f"/v1/apps/{app_key}/publish",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "manifest": manifest_v1,
                "artifact": {"ref": f"capsules/{app_key}/artifacts/v1.tar.gz", "sha256": "abc123"},
                "change_description": "Initial v1 release",
            },
        )
        assert pub1_res.status_code == 202, pub1_res.text
        v1_op = pub1_res.json()
        assert v1_op["status"] == "succeeded"
        v1_id = v1_op["version_id"]

        # Initialize SQLite database with v1 data (3 items)
        conn = sqlite3.connect(str(live_db_file))
        conn.execute("CREATE TABLE todos (id INTEGER PRIMARY KEY, title TEXT, done BOOLEAN);")
        conn.execute("INSERT INTO todos (title, done) VALUES ('item 1', 0);")
        conn.execute("INSERT INTO todos (title, done) VALUES ('item 2', 1);")
        conn.execute("INSERT INTO todos (title, done) VALUES ('item 3', 0);")
        conn.commit()
        conn.close()

        # Verify live database has 3 items
        conn = sqlite3.connect(str(live_db_file))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM todos;")
        assert cur.fetchone()[0] == 3
        conn.close()

        # 3. Deploy v2 (with database snapshot taken before deploy)
        manifest_v2 = dict(manifest_v1)
        manifest_v2["roles"] = ["employee", "manager"]
        pub2_res = await client.post(
            f"/v1/apps/{app_key}/publish",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "manifest": manifest_v2,
                "artifact": {"ref": f"capsules/{app_key}/artifacts/v2.tar.gz", "sha256": "def456"},
                "change_description": "Version 2 release with manager role",
            },
        )
        assert pub2_res.status_code == 202, pub2_res.text
        v2_op = pub2_res.json()
        assert v2_op["status"] == "succeeded"

        # Verify v2 snapshot was taken and contains the 3 items
        v2_snapshot_ref = f"capsules/{app_id}/snapshots/v2_snapshot.sqlite"
        assert await storage.exists(v2_snapshot_ref)

        # Now write new data in v2: add 2 more items (total 5 items)
        conn = sqlite3.connect(str(live_db_file))
        conn.execute("INSERT INTO todos (title, done) VALUES ('item 4', 0);")
        conn.execute("INSERT INTO todos (title, done) VALUES ('item 5', 1);")
        conn.commit()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM todos;")
        assert cur.fetchone()[0] == 5
        conn.close()

        # 4. Roll back to v1 code-only
        rb_code_res = await client.post(
            f"/v1/apps/{app_key}/rollback",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "target_version_number": 1,
                "mode": "code_only",
                "reason": "Revert code for testing",
            },
        )
        assert rb_code_res.status_code == 202, rb_code_res.text
        rb_code = rb_code_res.json()
        assert rb_code["version_number"] == 3
        assert rb_code["target_version_number"] == 1
        assert rb_code["mode"] == "code_only"
        assert rb_code["data_restored"] is False

        # Verify live database data is preserved: still 5 items!
        conn = sqlite3.connect(str(live_db_file))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM todos;")
        assert cur.fetchone()[0] == 5
        conn.close()

        # 5. Test Incompatible Schema Rejection for code-only rollback
        # Break schema by dropping a required column/table
        conn = sqlite3.connect(str(live_db_file))
        conn.execute("DROP TABLE todos;")
        conn.execute("CREATE TABLE other_table (id INTEGER PRIMARY KEY);")
        conn.commit()
        conn.close()

        rb_incompat_res = await client.post(
            f"/v1/apps/{app_key}/rollback",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "target_version_number": 2,
                "mode": "code_only",
            },
        )
        assert rb_incompat_res.status_code == 422
        incompat_err = rb_incompat_res.json()["detail"]
        assert incompat_err["code"] == "ROLLBACK_INCOMPATIBLE"

        # Restore todos table with 5 items
        conn = sqlite3.connect(str(live_db_file))
        conn.execute("DROP TABLE other_table;")
        conn.execute("CREATE TABLE todos (id INTEGER PRIMARY KEY, title TEXT, done BOOLEAN);")
        for i in range(1, 6):
            conn.execute("INSERT INTO todos (title, done) VALUES (?, 0);", (f"item {i}",))
        conn.commit()
        conn.close()

        # 6. Test Code + Data Restore Warning without Confirmation
        rb_warn_res = await client.post(
            f"/v1/apps/{app_key}/rollback",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "target_version_number": 2,
                "mode": "code_and_data",
                "confirm_data_restore": False,
            },
        )
        assert rb_warn_res.status_code == 422
        warn_data = rb_warn_res.json()["detail"]
        assert warn_data["code"] == "CONFIRMATION_REQUIRED"
        assert "data_loss_warning" in warn_data
        warning = warn_data["data_loss_warning"]
        assert warning["target_version"] == 2
        assert warning["current_records"] == 5
        assert warning["target_records"] == 3
        assert warning["estimated_records_lost"] == 2
        assert warning["recovery_snapshot_available"] is True

        # 7. Test Code + Data Restore WITH Confirmation
        rb_data_res = await client.post(
            f"/v1/apps/{app_key}/rollback",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "target_version_number": 2,
                "mode": "code_and_data",
                "confirm_data_restore": True,
                "reason": "Restoring data from v2 snapshot",
            },
        )
        assert rb_data_res.status_code == 202, rb_data_res.text
        rb_data = rb_data_res.json()
        assert rb_data["version_number"] == 4
        assert rb_data["target_version_number"] == 2
        assert rb_data["mode"] == "code_and_data"
        assert rb_data["data_restored"] is True
        recovery_ref_v4 = rb_data["recovery_snapshot_ref"]
        assert await storage.exists(recovery_ref_v4)

        # Verify live database now has exactly 3 items from v2 snapshot
        conn = sqlite3.connect(str(live_db_file))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM todos;")
        assert cur.fetchone()[0] == 3
        conn.close()

        # 8. Undo the Rollback: Roll forward to the pre-rollback recovery version (v4's recovery snapshot)
        # In v4, recovery_snapshot_ref captured the 5 items that were present right before the data restore!
        undo_res = await client.post(
            f"/v1/apps/{app_key}/rollback",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "target_version_number": 4,
                "mode": "code_and_data",
                "confirm_data_restore": True,
                "reason": "Undo previous data restore",
            },
        )
        assert undo_res.status_code == 202, undo_res.text
        undo_op = undo_res.json()
        assert undo_op["version_number"] == 5
        assert undo_op["target_version_number"] == 4
        assert undo_op["data_restored"] is True

        # Verify all 5 items are restored: NO DATA LOST SILENTLY!
        conn = sqlite3.connect(str(live_db_file))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM todos;")
        assert cur.fetchone()[0] == 5
        conn.close()

        # 9. Check Version History Endpoint contains all details
        ver_res = await client.get(f"/v1/apps/{app_key}/versions", headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"})
        assert ver_res.status_code == 200
        ver_list = ver_res.json()["items"]
        assert len(ver_list) == 5
        # Verify version numbers in descending order: 5, 4, 3, 2, 1
        assert [v["version_number"] for v in ver_list] == [5, 4, 3, 2, 1]
        for v in ver_list:
            assert v["db_snapshot_ref"] is not None
            assert v["status"] in ("published", "rolled_back")

        # 10. Scoped Publish Token Cannot Perform Rollback
        token_res = await client.post(
            "/v1/tokens/publish",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={"app_id": app_id, "scope": "app:publish", "expires_in_seconds": 3600},
        )
        assert token_res.status_code == 200
        publish_token = token_res.json()["token"]

        pub_token_rb = await client.post(
            f"/v1/apps/{app_key}/rollback",
            headers={"Authorization": f"Bearer {publish_token}"},
            json={"target_version_number": 1, "mode": "code_only"},
        )
        assert pub_token_rb.status_code == 403
        assert pub_token_rb.json()["detail"]["code"] == "FORBIDDEN"
