"""Le moteur ne doit jamais laisser de valeur brute dans le message d'une erreur SQL."""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.website import Website

SENTINEL = "sentinelle-valeur-brute-a-ne-jamais-loguer.test"


async def test_sql_parameters_are_hidden_from_database_errors(db_session: AsyncSession) -> None:
    # Clé étrangère inexistante : la base rejette l'insertion, avec les paramètres en jeu.
    db_session.add(Website(workspace_id=uuid4(), domain=SENTINEL, display_name=SENTINEL))
    with pytest.raises(IntegrityError) as caught:
        await db_session.flush()
    assert SENTINEL not in str(caught.value)
    assert "[parameters:" not in str(caught.value)
    assert SENTINEL not in repr(caught.value)
