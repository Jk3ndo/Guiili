from httpx import AsyncClient


async def test_health_db_ok(client: AsyncClient) -> None:
    response = await client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == {"database": "ok"}
