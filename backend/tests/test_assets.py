"""
Tests for /api/v1/assets — CMDB-lite CRUD.

Coverage:
  - Auth: unauthenticated → 401; non-admin POST/PATCH/DELETE → 403
  - POST   /assets/         admin creates asset → 201
  - GET    /assets/         any authenticated user gets list → 200
  - GET    /assets/search   q-param autocomplete → 200
  - GET    /assets/{id}     any authenticated user → 200 / 404
  - PATCH  /assets/{id}     admin updates fields → 200
  - DELETE /assets/{id}     204 when no tickets; 409 when tickets reference it
  - Duplicate serial_number → 409
  - Invalid asset_type / status → 422
"""

import os

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# serial_number uniqueness is enforced by a partial PostgreSQL index —
# not enforceable in SQLite. Skip these checks when running locally on SQLite.
_requires_postgres = pytest.mark.skipif(
    "sqlite" in os.getenv("TEST_DATABASE_URL", "sqlite"),
    reason="partial unique index on serial_number only works on PostgreSQL",
)

# ── Helpers ───────────────────────────────────────────────────────────────────


async def _register_user(client: AsyncClient, suffix: str) -> tuple[int, str]:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"assetuser{suffix}@example.com",
            "username": f"assetuser{suffix}",
            "password": "Secret123!",
        },
    )
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    return me.json()["id"], token


async def _register_admin(client: AsyncClient, suffix: str) -> tuple[int, str]:
    from app.config import get_settings

    settings = get_settings()
    admin_email = f"assetadmin{suffix}@example.com"
    prev = settings.BOOTSTRAP_ADMIN_EMAIL
    settings.BOOTSTRAP_ADMIN_EMAIL = admin_email
    try:
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": admin_email,
                "username": f"assetadmin{suffix}",
                "password": "Secret123!",
            },
        )
    finally:
        settings.BOOTSTRAP_ADMIN_EMAIL = prev
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["role"] == "admin"
    return me.json()["id"], token


_VALID_ASSET = {
    "asset_type": "laptop",
    "name": "MacBook Pro 14",
    "serial_number": "SN-ABCDE-001",
    "office": "Moscow",
    "status": "active",
    "notes": "Assigned to QA team",
}


async def _create_asset(
    client: AsyncClient,
    token: str,
    overrides: dict | None = None,
) -> dict:
    payload = {**_VALID_ASSET, **(overrides or {})}
    resp = await client.post(
        "/api/v1/assets/",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    return resp.json()


# ── Auth / permissions ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_assets_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/assets/")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_asset_by_id_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/assets/999")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_search_assets_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/assets/search?q=laptop")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_asset_requires_admin(client: AsyncClient):
    _, token = await _register_user(client, "createforbidden")
    resp = await client.post(
        "/api/v1/assets/",
        json=_VALID_ASSET,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_asset_requires_admin(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    _, admin_token = await _register_admin(client, "patchadm")
    _, user_token = await _register_user(client, "patchusr")

    asset = await _create_asset(client, admin_token, {"serial_number": "SN-PATCH-PERM"})
    resp = await client.patch(
        f"/api/v1/assets/{asset['id']}",
        json={"name": "Hacked"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_asset_requires_admin(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    _, admin_token = await _register_admin(client, "deladm")
    _, user_token = await _register_user(client, "delusr")

    asset = await _create_asset(client, admin_token, {"serial_number": "SN-DEL-PERM"})
    resp = await client.delete(
        f"/api/v1/assets/{asset['id']}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


# ── POST /assets/ ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_can_create_asset(client: AsyncClient):
    _, token = await _register_admin(client, "create01")

    resp = await client.post(
        "/api/v1/assets/",
        json=_VALID_ASSET,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["asset_type"] == "laptop"
    assert data["name"] == "MacBook Pro 14"
    assert data["serial_number"] == "SN-ABCDE-001"
    assert data["office"] == "Moscow"
    assert data["status"] == "active"
    assert data["notes"] == "Assigned to QA team"
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_create_asset_without_serial(client: AsyncClient):
    """serial_number is optional — multiple assets with NULL are allowed."""
    _, token = await _register_admin(client, "create02")

    resp = await client.post(
        "/api/v1/assets/",
        json={"asset_type": "monitor", "name": "Dell 27inch", "status": "active"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["serial_number"] is None


@pytest.mark.asyncio
async def test_create_asset_invalid_type_returns_422(client: AsyncClient):
    _, token = await _register_admin(client, "create03")

    resp = await client.post(
        "/api/v1/assets/",
        json={"asset_type": "spaceship", "name": "UFO", "status": "active"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_asset_invalid_status_returns_422(client: AsyncClient):
    _, token = await _register_admin(client, "create04")

    resp = await client.post(
        "/api/v1/assets/",
        json={"asset_type": "laptop", "name": "X", "status": "flying"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@_requires_postgres
@pytest.mark.asyncio
async def test_create_asset_duplicate_serial_returns_409(client: AsyncClient):
    """Two assets with the same non-NULL serial_number are rejected.

    Enforced by partial unique index — PostgreSQL only.
    """
    _, token = await _register_admin(client, "create05")

    await _create_asset(client, token, {"serial_number": "SN-DUP-001"})

    resp = await client.post(
        "/api/v1/assets/",
        json={**_VALID_ASSET, "serial_number": "SN-DUP-001"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_asset_invalid_owner_returns_422(client: AsyncClient):
    _, token = await _register_admin(client, "create06")

    resp = await client.post(
        "/api/v1/assets/",
        json={**_VALID_ASSET, "owner_user_id": 999_999, "serial_number": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_asset_with_owner(client: AsyncClient):
    _, admin_token = await _register_admin(client, "create07")
    user_id, _ = await _register_user(client, "create07usr")

    resp = await client.post(
        "/api/v1/assets/",
        json={
            "asset_type": "phone",
            "name": "iPhone 15",
            "status": "active",
            "owner_user_id": user_id,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["owner_user_id"] == user_id


# ── GET /assets/ ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_assets_accessible_to_regular_user(client: AsyncClient):
    """Any authenticated user (not just admin) can list assets."""
    _, admin_token = await _register_admin(client, "list01adm")
    _, user_token = await _register_user(client, "list01usr")

    await _create_asset(client, admin_token, {"serial_number": "SN-LIST-001"})

    resp = await client.get(
        "/api/v1/assets/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_list_assets_filter_by_type(client: AsyncClient):
    _, token = await _register_admin(client, "list02")

    await _create_asset(client, token, {"asset_type": "server", "serial_number": "SN-SRV-001"})
    await _create_asset(client, token, {"asset_type": "printer", "serial_number": "SN-PRN-001"})

    resp = await client.get(
        "/api/v1/assets/?asset_type=server",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assets = resp.json()
    assert all(a["asset_type"] == "server" for a in assets)


@pytest.mark.asyncio
async def test_list_assets_filter_by_status(client: AsyncClient):
    _, token = await _register_admin(client, "list03")

    await _create_asset(
        client, token, {"status": "in_repair", "serial_number": "SN-REPAIR-001"}
    )
    await _create_asset(client, token, {"status": "active", "serial_number": "SN-ACTIVE-001"})

    resp = await client.get(
        "/api/v1/assets/?status=in_repair",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assets = resp.json()
    assert all(a["status"] == "in_repair" for a in assets)


@pytest.mark.asyncio
async def test_list_assets_invalid_type_returns_422(client: AsyncClient):
    _, token = await _register_user(client, "list04")
    resp = await client.get(
        "/api/v1/assets/?asset_type=flying_saucer",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ── GET /assets/search ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_assets_by_name(client: AsyncClient):
    _, admin_token = await _register_admin(client, "search01adm")
    _, user_token = await _register_user(client, "search01usr")

    await _create_asset(
        client,
        admin_token,
        {"name": "ThinkPad X1 Carbon", "serial_number": "SN-TPXC-001"},
    )

    resp = await client.get(
        "/api/v1/assets/search?q=ThinkPad",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    results = resp.json()
    assert any("ThinkPad" in a["name"] for a in results)


@pytest.mark.asyncio
async def test_search_assets_by_serial_number(client: AsyncClient):
    _, admin_token = await _register_admin(client, "search02adm")
    _, user_token = await _register_user(client, "search02usr")

    await _create_asset(
        client,
        admin_token,
        {"name": "HP EliteBook", "serial_number": "SN-UNIQUE-XYZ"},
    )

    resp = await client.get(
        "/api/v1/assets/search?q=UNIQUE-XYZ",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    results = resp.json()
    assert any(a["serial_number"] == "SN-UNIQUE-XYZ" for a in results)


@pytest.mark.asyncio
async def test_search_assets_requires_min_2_chars(client: AsyncClient):
    _, token = await _register_user(client, "search03")
    resp = await client.get(
        "/api/v1/assets/search?q=a",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ── GET /assets/{id} ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_asset_by_id(client: AsyncClient):
    _, admin_token = await _register_admin(client, "getid01adm")
    _, user_token = await _register_user(client, "getid01usr")

    asset = await _create_asset(client, admin_token, {"serial_number": "SN-GETID-001"})

    resp = await client.get(
        f"/api/v1/assets/{asset['id']}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == asset["id"]
    assert resp.json()["name"] == asset["name"]


@pytest.mark.asyncio
async def test_get_asset_not_found(client: AsyncClient):
    _, token = await _register_user(client, "getid02")
    resp = await client.get(
        "/api/v1/assets/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ── PATCH /assets/{id} ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_can_patch_asset(client: AsyncClient):
    _, token = await _register_admin(client, "patch01")

    asset = await _create_asset(client, token, {"serial_number": "SN-PATCH-001"})

    resp = await client.patch(
        f"/api/v1/assets/{asset['id']}",
        json={"name": "Updated Name", "status": "in_repair"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated Name"
    assert data["status"] == "in_repair"
    # Unchanged fields are preserved
    assert data["asset_type"] == asset["asset_type"]


@_requires_postgres
@pytest.mark.asyncio
async def test_patch_asset_duplicate_serial_returns_409(client: AsyncClient):
    """PATCH to an already-used serial_number returns 409 — PostgreSQL only."""
    _, token = await _register_admin(client, "patch02")

    await _create_asset(client, token, {"serial_number": "SN-PATDUP-A"})
    asset_b = await _create_asset(client, token, {"serial_number": "SN-PATDUP-B"})

    resp = await client.patch(
        f"/api/v1/assets/{asset_b['id']}",
        json={"serial_number": "SN-PATDUP-A"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_patch_nonexistent_asset_returns_404(client: AsyncClient):
    _, token = await _register_admin(client, "patch03")
    resp = await client.patch(
        "/api/v1/assets/999999",
        json={"name": "Ghost"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ── DELETE /assets/{id} ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_can_delete_asset_without_tickets(client: AsyncClient):
    _, token = await _register_admin(client, "del01")

    asset = await _create_asset(client, token, {"serial_number": "SN-DEL-CLEAN"})

    resp = await client.delete(
        f"/api/v1/assets/{asset['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204

    # Confirm gone
    get_resp = await client.get(
        f"/api/v1/assets/{asset['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_asset_blocked_when_tickets_reference_it(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """DELETE returns 409 if any tickets still have asset_id pointing to this asset.

    The router deliberately blocks deletion to preserve ticket history.
    """
    _, admin_token = await _register_admin(client, "del02adm")
    user_id, user_token = await _register_user(client, "del02usr")

    asset = await _create_asset(client, admin_token, {"serial_number": "SN-DEL-BUSY"})

    # Create a ticket that references the asset
    ticket_resp = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "Laptop broken",
            "body": "Screen cracked, need replacement",
            "user_priority": 3,
            "asset_id": asset["id"],
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert ticket_resp.status_code == 201

    # Now trying to delete the asset should fail
    del_resp = await client.delete(
        f"/api/v1/assets/{asset['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 409
    assert "ticket" in del_resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_nonexistent_asset_returns_404(client: AsyncClient):
    _, token = await _register_admin(client, "del03")
    resp = await client.delete(
        "/api/v1/assets/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ── Ticket ↔ Asset linkage ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ticket_read_includes_asset_summary(client: AsyncClient):
    """TicketRead.asset should be populated when asset_id is set."""
    _, admin_token = await _register_admin(client, "link01adm")
    _, user_token = await _register_user(client, "link01usr")

    asset = await _create_asset(
        client, admin_token, {"serial_number": "SN-LINK-001", "name": "Test Laptop"}
    )

    ticket_resp = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "Cannot login",
            "body": "Getting 403 on startup",
            "user_priority": 3,
            "asset_id": asset["id"],
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert ticket_resp.status_code == 201
    ticket = ticket_resp.json()

    assert ticket["asset_id"] == asset["id"]
    assert ticket["asset"] is not None
    assert ticket["asset"]["id"] == asset["id"]
    assert ticket["asset"]["name"] == "Test Laptop"
    assert ticket["asset"]["asset_type"] == "laptop"
