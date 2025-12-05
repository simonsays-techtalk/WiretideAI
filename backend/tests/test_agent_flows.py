import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

sys.path.append(str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("WIRETIDE_ADMIN_TOKEN", "test-admin")
os.environ.setdefault("WIRETIDE_DATABASE_URL", "sqlite:///:memory:")

from wiretide.db import get_session  # noqa: E402
from wiretide.main import app  # noqa: E402
from wiretide.services import ensure_settings_seeded  # noqa: E402


test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def get_test_session():
    with Session(test_engine) as session:
        yield session


app.dependency_overrides[get_session] = get_test_session

# Disable production startup/shutdown hooks and lifespan for isolated testing.
app.router.on_startup.clear()
app.router.on_shutdown.clear()
app.router.lifespan_context = None


@pytest.fixture(autouse=True)
def clear_db():
    SQLModel.metadata.drop_all(test_engine)
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        ensure_settings_seeded(session)


client = TestClient(app)


def test_register_approve_queue_and_pop_config():
    token = client.get("/token/current").json()["shared_token"]
    reg = client.post(
        "/register",
        headers={"X-Shared-Token": token},
        json={"hostname": "demo-router", "ssh_enabled": True},
    )
    assert reg.status_code == 200
    device_id = reg.json()["device_id"]

    approve = client.post(
        "/api/devices/approve",
        headers={"X-Admin-Token": "test-admin"},
        json={"device_id": device_id, "device_type": "router"},
    )
    assert approve.status_code == 200

    new_token = client.get("/token/current").json()["shared_token"]
    assert new_token != token

    queue = client.post(
        "/api/queue-config",
        headers={"X-Admin-Token": "test-admin"},
        json={
            "device_id": device_id,
            "package": "wiretide.firewall",
            "package_json": {"profile": "strict"},
        },
    )
    assert queue.status_code == 200

    cfg = client.get(
        "/config",
        headers={"X-Shared-Token": new_token},
        params={"device_id": device_id},
    )
    assert cfg.status_code == 200
    assert cfg.json()["package_json"]["profile"] == "strict"

    # Second fetch should 404 because config is popped after delivery.
    cfg2 = client.get(
        "/config",
        headers={"X-Shared-Token": new_token},
        params={"device_id": device_id},
    )
    assert cfg2.status_code == 404


def test_admin_list_settings_and_token_regen():
    token = client.get("/token/current").json()["shared_token"]
    reg = client.post(
        "/register",
        headers={"X-Shared-Token": token},
        json={"hostname": "demo-router-2", "ssh_enabled": True},
    )
    device_id = reg.json()["device_id"]
    client.post(
        "/api/devices/approve",
        headers={"X-Admin-Token": "test-admin"},
        json={"device_id": device_id, "device_type": "router"},
    )

    devices = client.get(
        "/api/devices",
        headers={"X-Admin-Token": "test-admin"},
    )
    assert devices.status_code == 200
    payload = devices.json()
    assert payload["total"] >= 1
    assert any(d["hostname"] == "demo-router-2" for d in payload["items"])

    filtered = client.get(
        "/api/devices",
        headers={"X-Admin-Token": "test-admin"},
        params={"device_type": "router", "status": "approved", "search": "demo"},
    )
    assert filtered.status_code == 200
    filtered_payload = filtered.json()
    assert filtered_payload["total"] >= 1
    assert all(item["device_type"] == "router" for item in filtered_payload["items"])

    # Block and remove transitions
    block = client.post(
        "/api/devices/block",
        headers={"X-Admin-Token": "test-admin"},
        params={"device_id": device_id},
    )
    assert block.status_code == 200
    assert block.json()["status"] == "blocked"

    remove = client.delete(
        f"/api/devices/{device_id}",
        headers={"X-Admin-Token": "test-admin"},
    )
    assert remove.status_code == 200
    assert remove.json()["removed"] == device_id

    detail = client.get(
        f"/api/devices/{device_id}",
        headers={"X-Admin-Token": "test-admin"},
    )
    assert detail.status_code == 404

    settings_before = client.get(
        "/api/settings",
        headers={"X-Admin-Token": "test-admin"},
    )
    assert settings_before.status_code == 200
    old_token = settings_before.json()["shared_token"]

    regen = client.post(
        "/api/settings/token/regenerate",
        headers={"X-Admin-Token": "test-admin"},
    )
    assert regen.status_code == 200
    assert regen.json()["shared_token"] != old_token

    policy = client.patch(
        "/api/settings/agent-update",
        headers={"X-Admin-Token": "test-admin"},
        json={
            "agent_update_policy": "off",
            "agent_update_url": None,
            "agent_min_version": None,
        },
    )
    assert policy.status_code == 200
    assert policy.json()["agent_update_policy"] == "off"

    monitoring = client.patch(
        "/api/settings/monitoring",
        headers={"X-Admin-Token": "test-admin"},
        json={"monitoring_api_enabled": True},
    )
    assert monitoring.status_code == 200
    assert monitoring.json()["monitoring_api_enabled"] is True
