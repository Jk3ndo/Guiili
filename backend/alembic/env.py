import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401 — peuple Base.metadata
from alembic import context
from app.config import get_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Les 7 enums utilisent Enum(native_enum=False, create_constraint=True) : la
# CHECK est « type-bound » et SQLAlchemy l'exclut de la comparaison côté
# métadonnées (all_table_check_constraints). Le comparateur
# `checkconstraint_byname` (Alembic >= 1.16) la voit alors uniquement côté base
# réfléchie et signale 7 faux « removed » à chaque `alembic check`.
#
# On désactive donc ce comparateur. CONSÉQUENCE : `alembic check` ne détecte
# plus AUCUNE dérive de CheckConstraint — ni les CHECK d'enums, ni une
# éventuelle CheckConstraint écrite à la main. C'est la même classe de
# compromis que `compare_server_default=False` : ces objets sont créés /
# supprimés avec leur table, et tout changement doit passer par une migration
# explicite.
#
# Garde-fou PARTIEL : tests/test_enum_check_constraints.py compare, pour chaque
# ck_* d'enum, les littéraux de la CHECK à {m.value for m in EnumClass}. Comme
# il lit une base construite par create_all() depuis les modèles, il attrape une
# régression du mapping values_callable (cf. le bug « ACTIVE » vs « active »),
# PAS une migration périmée : ajouter un membre d'enum sans régénérer la
# migration laisse toute la suite verte. Un vrai garde-fou de fraîcheur de
# migration doit tourner sur database_url_migrations_test après `alembic upgrade
# head` (machinerie dans test_migrations.py) — à faire avec le spec OAuth.
AUTOGENERATE_PLUGINS = (
    "alembic.autogenerate.*",
    "~alembic.autogenerate.checkconstraint_byname",
)


def _database_url() -> str:
    return os.environ.get("ALEMBIC_DATABASE_URL") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=False,
        autogenerate_plugins=AUTOGENERATE_PLUGINS,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=False,
        autogenerate_plugins=AUTOGENERATE_PLUGINS,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
