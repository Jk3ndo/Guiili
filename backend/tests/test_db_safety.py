import pytest

from tests.db_safety import assert_safe_test_database

PROD = "postgresql+asyncpg://u:p@host/control_center"


def test_accepts_dedicated_test_databases() -> None:
    assert_safe_test_database("X", "postgresql+asyncpg://u:p@h/control_center_test", PROD)
    assert_safe_test_database("X", "postgresql+asyncpg://u:p@h/cc_migrations?ssl=require", PROD)


@pytest.mark.parametrize(
    "url",
    [
        "",
        PROD,
        "postgresql+asyncpg://u:p@other/control_center",
        "postgresql+asyncpg://u:p@h/neondb",
        "postgresql+asyncpg://u:p@h/prod_test_backup_live",
    ],
)
def test_refuses_anything_that_is_not_a_disposable_database(url: str) -> None:
    with pytest.raises(RuntimeError):
        assert_safe_test_database("DATABASE_URL_TEST", url, PROD)
