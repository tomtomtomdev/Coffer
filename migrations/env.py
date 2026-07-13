"""Alembic environment.

The database URL is read from the environment (``COFFER_DATABASE_URL``), never from
alembic.ini — no connection string lives in the repo (SPEC §6). ``target_metadata``
is the ORM models' metadata so ``--autogenerate`` and the up/down tests see the full
SPEC §2 schema.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from coffer.persistence.config import Settings
from coffer.persistence.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the real URL from the environment (overrides the placeholder in alembic.ini).
config.set_main_option("sqlalchemy.url", Settings.from_env().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
