import configparser
import importlib
import importlib.util
import logging
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from backend.app.database import (
    Base,
    create_db_engine,
    get_engine_options,
    get_engine_for_url,
    ensure_schema_migrations,
    set_sqlite_pragma,
)


def test_sqlite_engine_options():
    """Verify engine options for file-based and in-memory SQLite URLs."""
    file_opts = get_engine_options("sqlite:///some_file.db")
    assert file_opts.get("connect_args") == {"check_same_thread": False}
    assert "poolclass" not in file_opts

    mem_opts = get_engine_options("sqlite:///:memory:")
    assert mem_opts.get("connect_args") == {"check_same_thread": False}
    assert mem_opts.get("poolclass") is StaticPool


def test_sqlite_engine_creation_and_pragmas():
    """Verify SQLite engine creation attaches WAL and concurrency pragmas."""
    eng = create_db_engine("sqlite:///:memory:")
    with eng.connect() as conn:
        sync_mode = conn.execute(text("PRAGMA synchronous")).scalar()
        busy_to = conn.execute(text("PRAGMA busy_timeout")).scalar()
        # synchronous=NORMAL maps to integer 1
        assert sync_mode == 1
        assert busy_to == 5000
    eng.dispose()


def test_postgresql_engine_options():
    """Verify PostgreSQL engine options configure pooling and strip check_same_thread."""
    for url in [
        "postgresql://opsdesk:opsdesk_password@localhost:5432/opsdesk",
        "postgresql+psycopg://opsdesk:opsdesk_password@localhost:5432/opsdesk",
    ]:
        opts = get_engine_options(url)
        assert opts.get("pool_size") == 10
        assert opts.get("max_overflow") == 20
        assert opts.get("pool_pre_ping") is True
        assert opts.get("pool_timeout") == 30
        if "connect_args" in opts:
            assert "check_same_thread" not in opts["connect_args"]


def test_postgresql_engine_creation_mocked_dbapi():
    """Verify PostgreSQL engine creation pool settings without needing live PostgreSQL."""
    mock_psycopg = MagicMock()
    mock_adapt = MagicMock()
    with patch.dict(sys.modules, {"psycopg": mock_psycopg, "psycopg.adapt": mock_adapt}):
        for url in [
            "postgresql+psycopg://opsdesk:opsdesk_password@localhost:5432/opsdesk",
            "postgresql://opsdesk:opsdesk_password@localhost:5432/opsdesk",
        ]:
            eng = create_db_engine(url)
            assert eng.pool.size() == 10
            assert eng.pool._max_overflow == 20
            assert eng.pool._timeout == 30
            assert eng.pool._pre_ping is True


def test_ensure_schema_migrations_success_logging(caplog):
    """Verify ensure_schema_migrations logs activities at INFO level."""
    eng = create_db_engine("sqlite:///:memory:")
    with caplog.at_level(logging.INFO, logger="opsdesk.database"):
        ensure_schema_migrations(eng)
    assert "Starting schema verification and lightweight migrations" in caplog.text
    assert "Base metadata create_all completed successfully." in caplog.text
    assert "SQLite lightweight schema migration completed successfully." in caplog.text
    eng.dispose()


def test_ensure_schema_migrations_reraises_and_logs_error(caplog):
    """Verify ensure_schema_migrations logs with logger.error and re-raises on fatal failures."""
    mock_engine = MagicMock()
    mock_engine.dialect.name = "sqlite"
    mock_engine.connect.side_effect = OperationalError("syntax error", params=None, orig=Exception("bad sql"))

    with caplog.at_level(logging.ERROR, logger="opsdesk.database"):
        with pytest.raises(OperationalError):
            ensure_schema_migrations(mock_engine)

    assert "Schema migration failed on engine" in caplog.text


def test_alembic_ini_exists_and_configured():
    """Verify alembic.ini exists in project root with valid script_location."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    ini_path = os.path.join(root_dir, "alembic.ini")
    assert os.path.isfile(ini_path), f"alembic.ini not found at {ini_path}"

    parser = configparser.ConfigParser()
    parser.read(ini_path)
    assert parser.has_section("alembic"), "alembic.ini missing [alembic] section"
    assert parser.get("alembic", "script_location") == "backend/alembic"


def test_alembic_env_py_exists_and_loadable():
    """Verify backend/alembic/env.py exists and references Base.metadata without importing outside alembic context."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env_path = os.path.join(root_dir, "backend", "alembic", "env.py")
    assert os.path.isfile(env_path), f"env.py not found at {env_path}"

    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "target_metadata = Base.metadata" in content
    assert "from backend.app.models import Base" in content

    # Verify model Base contains expected tables without executing env.py top-level code
    expected_tables = {
        "agencies",
        "users",
        "tickets",
        "events_outbox",
        "ticket_links",
        "ticket_messages",
        "side_conversations",
        "side_conversation_recipients",
        "side_conversation_messages",
        "ticket_themes",
        "audit_logs",
        "idempotency_records",
    }
    actual_tables = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(actual_tables), f"Missing tables: {expected_tables - actual_tables}"


def test_alembic_baseline_revision_structure():
    """Verify 0001_baseline_schema.py revision exports upgrade and downgrade functions."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    rev_path = os.path.join(root_dir, "backend", "alembic", "versions", "0001_baseline_schema.py")
    assert os.path.isfile(rev_path), f"baseline revision not found at {rev_path}"

    rev_module = importlib.import_module("backend.alembic.versions.0001_baseline_schema")
    assert rev_module.revision == "0001_baseline_schema"
    assert rev_module.down_revision is None
    assert callable(rev_module.upgrade)
    assert callable(rev_module.downgrade)


def test_alembic_baseline_revision_mock_execution():
    """Verify baseline schema creates all 12 tables and drops them in downgrade."""
    rev_module = importlib.import_module("backend.alembic.versions.0001_baseline_schema")

    created_tables = []
    created_indexes = []
    dropped_tables = []

    mock_op = MagicMock()
    mock_op.create_table.side_effect = lambda name, *args, **kwargs: created_tables.append(name)
    mock_op.create_index.side_effect = lambda name, table, *args, **kwargs: created_indexes.append(name)
    mock_op.drop_table.side_effect = lambda name: dropped_tables.append(name)

    with patch.object(rev_module, "op", mock_op):
        rev_module.upgrade()
        assert len(created_tables) == 12
        for table in [
            "agencies", "users", "tickets", "events_outbox", "ticket_links",
            "ticket_messages", "side_conversations", "side_conversation_recipients",
            "side_conversation_messages", "ticket_themes", "audit_logs", "idempotency_records"
        ]:
            assert table in created_tables

        assert "ix_tickets_queue_score" in created_indexes
        assert "ix_tickets_effective_deadline_at" in created_indexes

        rev_module.downgrade()
        assert len(dropped_tables) == 12
        # Verify foreign-key safe reverse drop order
        assert dropped_tables[0] == "idempotency_records"
        assert dropped_tables[-1] == "agencies"


def test_alembic_revision_0002_structure_and_mock_execution():
    """Verify 0002_timezone_aware_and_queue_score.py revision exports valid upgrade and downgrade."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    rev_path = os.path.join(root_dir, "backend", "alembic", "versions", "0002_timezone_aware_and_queue_score.py")
    assert os.path.isfile(rev_path), f"revision 0002 not found at {rev_path}"

    rev_module = importlib.import_module("backend.alembic.versions.0002_timezone_aware_and_queue_score")
    assert rev_module.revision == "0002_timezone_aware_and_queue_score"
    assert rev_module.down_revision == "0001_baseline_schema"
    assert callable(rev_module.upgrade)
    assert callable(rev_module.downgrade)

    mock_op = MagicMock()
    mock_batch = MagicMock()
    mock_op.batch_alter_table.return_value.__enter__.return_value = mock_batch
    mock_bind = MagicMock()
    mock_bind.dialect.name = "sqlite"
    mock_op.get_bind.return_value = mock_bind

    with patch.object(rev_module, "op", mock_op):
        rev_module.upgrade()
        assert mock_batch.add_column.called

        rev_module.downgrade()
        assert mock_batch.drop_column.called


def test_alembic_cli_upgrade_downgrade_sqlite():
    """Run alembic upgrade head and downgrade base against isolated temp DB."""
    if importlib.util.find_spec("alembic") is None:
        pytest.skip("Alembic package is not installed; skipping CLI upgrade/downgrade execution.")

    from alembic.config import Config
    from alembic import command

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    try:
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        ini_path = os.path.join(root_dir, "alembic.ini")
        dev_db_path = os.path.join(root_dir, "opsdesk.db")
        mtime_before = os.path.getmtime(dev_db_path) if os.path.exists(dev_db_path) else None

        alembic_cfg = Config(ini_path)
        normalized_path = temp_db_path.replace("\\", "/")
        temp_db_url = f"sqlite:///{normalized_path}"
        alembic_cfg.set_main_option("sqlalchemy.url", temp_db_url)

        command.upgrade(alembic_cfg, "head")

        if mtime_before is not None and os.path.exists(dev_db_path):
            assert os.path.getmtime(dev_db_path) == mtime_before, "Alembic CLI test modified opsdesk.db mtime!"

        eng = create_db_engine(temp_db_url)
        with eng.connect() as conn:
            tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            table_names = [t[0] for t in tables]
            assert "tickets" in table_names
            assert "agencies" in table_names
            assert "alembic_version" in table_names
        eng.dispose()

        command.downgrade(alembic_cfg, "base")

        if mtime_before is not None and os.path.exists(dev_db_path):
            assert os.path.getmtime(dev_db_path) == mtime_before, "Alembic CLI test modified opsdesk.db mtime!"

        eng2 = create_db_engine(temp_db_url)
        with eng2.connect() as conn:
            tables2 = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            table_names2 = [t[0] for t in tables2]
            assert "tickets" not in table_names2
            assert "agencies" not in table_names2
        eng2.dispose()
    finally:
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except Exception:
                pass
