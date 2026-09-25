from httpx import AsyncClient

from app.config import get_settings
from app.models.user import User


async def _register(client: AsyncClient, email: str) -> int:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Motdepasse-solide-1", "display_name": "T"},
    )
    return resp.status_code


async def test_login_blocks_after_ten_failures_per_email(db_client: AsyncClient) -> None:
    await _register(db_client, "victime@example.com")
    db_client.cookies.clear()
    for _ in range(10):
        resp = await db_client.post(
            "/api/v1/auth/login", json={"email": "victime@example.com", "password": "mauvais"}
        )
        assert resp.status_code == 400
    blocked = await db_client.post(
        "/api/v1/auth/login", json={"email": "victime@example.com", "password": "mauvais"}
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    # Même le bon mot de passe est refusé pendant le blocage (force brute).
    good = await db_client.post(
        "/api/v1/auth/login",
        json={"email": "victime@example.com", "password": "Motdepasse-solide-1"},
    )
    assert good.status_code == 429
    # Une autre adresse n'est pas touchée.
    other = await db_client.post(
        "/api/v1/auth/login", json={"email": "autre@example.com", "password": "x"}
    )
    assert other.status_code == 400


async def test_successful_logins_do_not_consume_the_failure_budget(
    db_client: AsyncClient,
) -> None:
    await _register(db_client, "ok@example.com")
    for _ in range(12):
        resp = await db_client.post(
            "/api/v1/auth/login",
            json={"email": "ok@example.com", "password": "Motdepasse-solide-1"},
        )
        assert resp.status_code == 200


async def test_register_is_limited_per_ip(db_client: AsyncClient) -> None:
    statuses = [await _register(db_client, f"u{i}@example.com") for i in range(11)]
    assert statuses[:10] == [201] * 10
    assert statuses[10] == 429


async def test_password_reset_request_is_limited_per_email_without_leaking(
    db_client: AsyncClient,
) -> None:
    codes = []
    for _ in range(6):
        resp = await db_client.post(
            "/api/v1/auth/password-reset/request", json={"email": "inconnu@example.com"}
        )
        codes.append(resp.status_code)
    assert codes == [200] * 5 + [429]  # même comportement pour un e-mail inexistant


async def test_user_limited_route_returns_429_after_the_quota(
    authed_client: tuple[AsyncClient, User],
) -> None:
    client, _ = authed_client
    fake = "00000000-0000-0000-0000-000000000000"
    codes = [
        (await client.post(f"/api/v1/websites/{fake}/gtm/headless")).status_code
        for _ in range(4)
    ]
    assert codes == [404, 404, 404, 429]


async def test_limits_can_be_disabled_by_setting(
    db_client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", False)
    statuses = [await _register(db_client, f"d{i}@example.com") for i in range(12)]
    assert 429 not in statuses
