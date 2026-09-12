from app.models.workspace_member import WorkspaceMember
from tests.conftest import owner_workspace_id


async def test_list_my_workspaces(authed_client, db_session) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    resp = await client.get("/api/v1/workspaces/mine")
    assert resp.status_code == 200
    body = resp.json()
    assert any(w["id"] == str(ws_id) and w["role"] == "owner" for w in body)


async def test_owner_can_invite(authed_client, db_session) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/invitations", json={"invited_email": "guest@example.com"}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["invited_email"] == "guest@example.com"


async def test_non_member_cannot_invite(authed_client, db_session, make_user) -> None:
    client, _ = authed_client
    stranger = await make_user(sub="stranger")
    stranger_ws_id = await owner_workspace_id(db_session, stranger)

    # L'utilisateur authentifie n'est pas membre du workspace de "stranger".
    resp = await client.post(
        f"/api/v1/workspaces/{stranger_ws_id}/invitations", json={"invited_email": "x@example.com"}
    )
    assert resp.status_code == 404


async def test_get_invitation_by_token(authed_client, db_session) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    created = await client.post(
        f"/api/v1/workspaces/{ws_id}/invitations", json={"invited_email": "guest2@example.com"}
    )
    token = created.json()["token"]
    resp = await client.get(f"/api/v1/invitations/{token}")
    assert resp.status_code == 200
    assert resp.json()["invited_email"] == "guest2@example.com"


async def test_accept_invitation_via_endpoint(authed_client, db_session, db_client) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    created = await client.post(
        f"/api/v1/workspaces/{ws_id}/invitations", json={"invited_email": "newmember@example.com"}
    )
    token = created.json()["token"]

    register = await db_client.post(
        "/api/v1/auth/register",
        json={"email": "newmember@example.com", "password": "correct horse battery staple", "display_name": "N"},
    )
    assert register.status_code == 201

    resp = await db_client.post(f"/api/v1/invitations/{token}/accept")
    assert resp.status_code == 200

    mine = await db_client.get("/api/v1/workspaces/mine")
    assert any(w["id"] == str(ws_id) for w in mine.json())


async def test_owner_can_remove_member(authed_client, db_session, make_user) -> None:
    client, owner = authed_client
    ws_id = await owner_workspace_id(db_session, owner)
    member_user = await make_user(sub="member-1", email="m1@example.com")
    db_session.add(WorkspaceMember(workspace_id=ws_id, user_id=member_user.id, role="member"))
    await db_session.flush()

    resp = await client.delete(f"/api/v1/workspaces/{ws_id}/members/{member_user.id}")
    assert resp.status_code == 204


async def test_owner_cannot_remove_self(authed_client, db_session) -> None:
    client, owner = authed_client
    ws_id = await owner_workspace_id(db_session, owner)
    resp = await client.delete(f"/api/v1/workspaces/{ws_id}/members/{owner.id}")
    assert resp.status_code == 400
