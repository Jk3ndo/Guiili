from httpx import AsyncClient


async def test_health_db_ok(db_client: AsyncClient) -> None:
    response = await db_client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == {"database": "ok"}
