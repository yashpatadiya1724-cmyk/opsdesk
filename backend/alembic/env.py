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

config = None
if context is not None:
    try:
        config = context.config
    except (AttributeError, Exception):
        config = None

    if config is not None:
        # Interpret the config file for Python logging.
        if config.config_file_name is not None:
            fileConfig(config.config_file_name)

        # 1. Check if an explicit URL was provided via -x url=...
        cmd_opts = context.get_x_argument(as_dictionary=True) if hasattr(context, "get_x_argument") else {}
        x_url = cmd_opts.get("url")

        # 2. Check if an explicitly provided URL was set via config.set_main_option or Config()
        current_url = config.get_main_option("sqlalchemy.url")

        if x_url and x_url.strip():
            config.set_main_option("sqlalchemy.url", x_url.strip().replace("%", "%%"))
        elif current_url and current_url.strip():
            # Explicitly provided URL wins
            pass
        else:
            # Fall back to DATABASE_URL when none was provided
            db_url = os.getenv("DATABASE_URL", DATABASE_URL)
            config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))


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
