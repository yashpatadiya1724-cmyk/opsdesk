import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

try:
    from alembic import context
except ImportError:
    context = None

# Ensure repo root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.app.config import DATABASE_URL
from backend.app.models import Base

# Target metadata for Alembic autogenerate
target_metadata = Base.metadata

if context is not None:
    config = context.config

    # Interpret the config file for Python logging.
    if config.config_file_name is not None:
        fileConfig(config.config_file_name)

    # Use DATABASE_URL from environment or fallback to application config
    db_url = os.getenv("DATABASE_URL", DATABASE_URL)
    config.set_main_option("sqlalchemy.url", db_url)
else:
    config = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    if context is None or config is None:
        return
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    if context is None or config is None:
        return

    # Use our database engine options if PostgreSQL or custom pooling
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context is not None:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()
