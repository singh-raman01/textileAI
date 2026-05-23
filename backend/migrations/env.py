import os
import sys
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Make sure the backend package is importable when Alembic runs
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.base import Base
from app.db import models  # noqa: F401 — ensures all models are registered

# Alembic Config object (provides access to values in alembic.ini)
config = context.config

# Interpret logging config from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for 'autogenerate' support
target_metadata = Base.metadata


def get_url() -> str:
    """
    Database URL: prefer the TEXTILE_DB_URL environment variable
    (set by main.py before Alembic runs), fallback to alembic.ini value.
    """
    return os.environ.get('TEXTILE_DB_URL') or config.get_main_option('sqlalchemy.url', '')


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url                     = url,
        target_metadata         = target_metadata,
        literal_binds           = True,
        dialect_opts            = {'paramstyle': 'named'},
        render_as_batch         = True,   # required for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration['sqlalchemy.url'] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix      = 'sqlalchemy.',
        poolclass   = pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection      = connection,
            target_metadata = target_metadata,
            render_as_batch = True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
