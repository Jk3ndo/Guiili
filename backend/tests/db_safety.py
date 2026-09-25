"""Garde-fou : la suite de tests détruit ses bases (`drop_all`, `downgrade base`).
Elle ne doit jamais pouvoir viser autre chose qu'une base jetable."""

from urllib.parse import urlsplit

_ALLOWED_SUFFIXES = ("_test", "_migrations")


def assert_safe_test_database(name: str, url: str, production_url: str) -> None:
    if not url:
        raise RuntimeError(
            f"{name} est vide : la suite de tests exige une base jetable dédiée "
            "(voir backend/.env.example)."
        )
    if url == production_url:
        raise RuntimeError(
            f"{name} est identique à DATABASE_URL : les tests détruiraient cette base."
        )
    database = urlsplit(url).path.rsplit("/", 1)[-1]
    if not database.endswith(_ALLOWED_SUFFIXES):
        raise RuntimeError(
            f"{name} vise la base « {database} » : seuls les noms finissant par "
            f"{' ou '.join(_ALLOWED_SUFFIXES)} sont autorisés pour les tests."
        )
