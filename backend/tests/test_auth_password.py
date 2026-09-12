from httpx import AsyncClient


async def test_register_creates_user_and_workspace(db_client: AsyncClient) -> None:
    resp = await db_client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": "correct horse battery staple", "display_name": "New"},
    )
    assert resp.status_code == 201, resp.text
    assert "cc_session" in resp.cookies


async def test_register_rejects_duplicate_password_email(
    db_client: AsyncClient, db_session
) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "password": "correct horse battery staple", "display_name": "Dup"},
    )
    resp = await db_client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "password": "another password here", "display_name": "Dup2"},
    )
    assert resp.status_code == 409


async def test_register_rejects_email_used_by_google_account(
    db_client: AsyncClient, db_session, make_user
) -> None:
    await make_user(sub="google-user", email="google@example.com")
    resp = await db_client.post(
        "/api/v1/auth/register",
        json={"email": "google@example.com", "password": "correct horse battery staple", "display_name": "X"},
    )
    assert resp.status_code == 409
    assert "google" in resp.json()["detail"].lower()


async def test_login_succeeds_with_correct_password(db_client: AsyncClient) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={"email": "login@example.com", "password": "correct horse battery staple", "display_name": "L"},
    )
    db_client.cookies.clear()
    resp = await db_client.post(
        "/api/v1/auth/login", json={"email": "login@example.com", "password": "correct horse battery staple"}
    )
    assert resp.status_code == 200
    assert "cc_session" in resp.cookies


async def test_login_rejects_wrong_password(db_client: AsyncClient) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={"email": "wrongpw@example.com", "password": "correct horse battery staple", "display_name": "W"},
    )
    db_client.cookies.clear()
    resp = await db_client.post(
        "/api/v1/auth/login", json={"email": "wrongpw@example.com", "password": "nope nope nope"}
    )
    assert resp.status_code == 400


async def test_login_rejects_google_only_account(db_client: AsyncClient, make_user) -> None:
    await make_user(sub="g-only", email="gonly@example.com")
    resp = await db_client.post(
        "/api/v1/auth/login", json={"email": "gonly@example.com", "password": "anything"}
    )
    assert resp.status_code == 400
    assert "google" in resp.json()["detail"].lower()


async def test_login_unknown_email_returns_400(db_client: AsyncClient) -> None:
    resp = await db_client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "anything"}
    )
    assert resp.status_code == 400


async def test_logout_clears_session_cookie(db_client: AsyncClient) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={"email": "logout@example.com", "password": "correct horse battery staple", "display_name": "O"},
    )
    resp = await db_client.post("/api/v1/auth/logout")
    assert resp.status_code == 204
    # Le cookie renvoye est vide/expire — httpx applique le Set-Cookie, donc
    # une requete authentifiee suivante echoue.
    me = await db_client.get("/api/v1/auth/me")
    assert me.status_code == 401
