"""Alembic migration environment.

The URL is the owner role's (KHATAIQ_MIGRATION_DATABASE_URL), never the app role's, unless a
caller such as the test suite already set sqlalchemy.url on the Config.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool, text

import khataiq.models  # noqa: F401  (registers every table on Base.metadata)
from khataiq.config import get_settings
from khataiq.db import Base

config = context.config
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_settings().migration_database_url)

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (alembic upgrade head --sql)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
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
        context.configure(
            connection=connection, target_metadata=target_metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()
        _set_app_role_password(connection)


def _set_app_role_password(connection: Connection) -> None:
    """Keep the app role's password out of migrations: set it from settings when given."""
    password = get_settings().app_db_password
    if password is None:
        return
    exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'khataiq_app'"))
    if exists.scalar() is None:
        return
    quoted = connection.execute(
        text("SELECT quote_literal(:p)"), {"p": password.get_secret_value()}
    ).scalar_one()
    connection.execute(text(f"ALTER ROLE khataiq_app PASSWORD {quoted}"))
    connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
