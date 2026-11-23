import configparser
import importlib
import importlib.util
import logging
import os
import sys
import tempfile
import subprocess
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

        assert "ix_tickets_tboh_id" in created_indexes
        assert "ix_tickets_check_in_date" in created_indexes

        rev_module.downgrade()
        assert len(dropped_tables) == 12
        # Verify foreign-key safe reverse drop order
        assert dropped_tables[0] == "idempotency_records"
        assert dropped_tables[-1] == "agencies"


def test_alembic_revision_0002_structure_and_mock_execution():
    """Verify 0002_tz_aware_priority_weight.py revision exports valid upgrade and downgrade."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    rev_path = os.path.join(root_dir, "backend", "alembic", "versions", "0002_tz_aware_priority_weight.py")
    assert os.path.isfile(rev_path), f"revision 0002 not found at {rev_path}"

    rev_module = importlib.import_module("backend.alembic.versions.0002_tz_aware_priority_weight")
    assert rev_module.revision == "0002_tz_aware_priority_weight"
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
        assert mock_op.batch_alter_table.called
        assert mock_op.execute.called

        rev_module.downgrade()
        assert mock_op.batch_alter_table.called


def test_alembic_revision_0003_structure_and_mock_execution():
    """Verify 0003_remove_stored_queue_score.py revision exports valid upgrade and downgrade."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    rev_path = os.path.join(root_dir, "backend", "alembic", "versions", "0003_remove_stored_queue_score.py")
    assert os.path.isfile(rev_path), f"revision 0003 not found at {rev_path}"

    rev_module = importlib.import_module("backend.alembic.versions.0003_remove_stored_queue_score")
    assert rev_module.revision == "0003_remove_stored_queue_score"
    assert rev_module.down_revision == "0002_tz_aware_priority_weight"
    assert callable(rev_module.upgrade)
    assert callable(rev_module.downgrade)

    mock_op = MagicMock()
    mock_batch = MagicMock()
    mock_op.batch_alter_table.return_value.__enter__.return_value = mock_batch

    with patch.object(rev_module, "op", mock_op), patch("sqlalchemy.inspect") as mock_inspect:
        mock_insp_obj = MagicMock()
        mock_insp_obj.get_columns.return_value = [{"name": "queue_score"}]
        mock_insp_obj.get_indexes.return_value = [{"name": "ix_tickets_queue_score"}]
        mock_inspect.return_value = mock_insp_obj

        rev_module.upgrade()
        assert mock_op.batch_alter_table.called
        assert mock_batch.drop_column.called

        rev_module.downgrade()
        assert mock_batch.add_column.called
        assert mock_batch.add_column.called

        rev_module.downgrade()
        assert mock_batch.drop_column.called


def test_alembic_revision_0004_structure_and_mock_execution():
    """Verify 0004_stored_queue_score_and_trigram.py revision exports valid upgrade and downgrade."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    rev_path = os.path.join(root_dir, "backend", "alembic", "versions", "0004_stored_queue_score_and_trigram.py")
    assert os.path.isfile(rev_path), f"revision 0004 not found at {rev_path}"

    rev_module = importlib.import_module("backend.alembic.versions.0004_stored_queue_score_and_trigram")
    assert rev_module.revision == "0004_stored_queue_score_trigram"
    assert rev_module.down_revision == "0003_remove_stored_queue_score"
    assert callable(rev_module.upgrade)
    assert callable(rev_module.downgrade)

    mock_op = MagicMock()
    mock_batch = MagicMock()
    mock_op.batch_alter_table.return_value.__enter__.return_value = mock_batch
    mock_bind = MagicMock()
    mock_bind.dialect.name = "postgresql"
    mock_op.get_bind.return_value = mock_bind

    with patch.object(rev_module, "op", mock_op), patch("sqlalchemy.inspect") as mock_inspect:
        mock_insp_obj = MagicMock()
        mock_insp_obj.get_columns.return_value = []
        mock_insp_obj.get_indexes.return_value = []
        mock_inspect.return_value = mock_insp_obj

        rev_module.upgrade()
        assert mock_op.batch_alter_table.called
        assert mock_batch.add_column.called
        assert mock_op.execute.called

        mock_insp_obj.get_columns.return_value = [{"name": "queue_score"}, {"name": "score_computed_at"}]
        mock_insp_obj.get_indexes.return_value = [{"name": "ix_tickets_status_assigned_score"}, {"name": "ix_tickets_queue_score"}]

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


def test_legacy_sqlite_db_upgrade_backfills_priority_weights():
    """Build a legacy-shaped SQLite DB, upgrade to head, and assert weights match priorities (not all 200)."""
    if importlib.util.find_spec("alembic") is None:
        pytest.skip("Alembic package is not installed; skipping migration test.")

    from alembic.config import Config
    from alembic import command

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    try:
        normalized_path = temp_db_path.replace("\\", "/")
        temp_db_url = f"sqlite:///{normalized_path}"

        # 1. Build legacy schema directly using DDL matching merge-base 7d39b66
        eng = create_db_engine(temp_db_url)
        with eng.connect() as conn:
            conn.execute(text("""
                CREATE TABLE agencies (
                    id VARCHAR(50) NOT NULL PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    country_code VARCHAR(10) NOT NULL,
                    tier VARCHAR(32) DEFAULT 'standard' NOT NULL
                )
            """))
            conn.execute(text("""
                CREATE TABLE users (
                    id VARCHAR(50) NOT NULL PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    email VARCHAR(200) NOT NULL UNIQUE,
                    role VARCHAR(50) NOT NULL,
                    region VARCHAR(50) NOT NULL,
                    is_available BOOLEAN DEFAULT 1,
                    agency_id VARCHAR(50) REFERENCES agencies(id) ON DELETE SET NULL
                )
            """))
            conn.execute(text("""
                CREATE TABLE tickets (
                    id VARCHAR(50) NOT NULL PRIMARY KEY,
                    tboh_id VARCHAR(100) NOT NULL,
                    agency_id VARCHAR(50) NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
                    title VARCHAR(300) NOT NULL,
                    description TEXT NOT NULL,
                    intent VARCHAR(100) DEFAULT 'Unclassified' NOT NULL,
                    priority VARCHAR(50) DEFAULT 'Medium' NOT NULL,
                    status VARCHAR(50) DEFAULT 'New' NOT NULL,
                    check_in_date DATETIME NOT NULL,
                    lcd_date DATETIME,
                    assigned_to VARCHAR(50) REFERENCES users(id) ON DELETE SET NULL,
                    routing_reason TEXT,
                    suggested_bug_link VARCHAR(200),
                    version INTEGER DEFAULT 1 NOT NULL,
                    created_at DATETIME,
                    updated_at DATETIME
                )
            """))

            # Insert legacy records
            conn.execute(text("INSERT INTO agencies (id, name, country_code, tier) VALUES ('AGY-LEGACY', 'Legacy Agency', 'AE', 'gold')"))
            conn.execute(text("INSERT INTO users (id, name, email, role, region, agency_id) VALUES ('USR-LEGACY', 'Legacy User', 'legacy@agency.com', 'Agent', 'MEA', 'AGY-LEGACY')"))
            conn.execute(text("""
                INSERT INTO tickets (id, tboh_id, agency_id, title, description, priority, status, check_in_date)
                VALUES 
                    ('TCK-U', 'TBOH-1', 'AGY-LEGACY', 'Urgent Ticket', 'Desc U', 'Urgent', 'New', '2026-11-20 12:00:00'),
                    ('TCK-H', 'TBOH-2', 'AGY-LEGACY', 'High Ticket', 'Desc H', 'High', 'New', '2026-11-21 12:00:00'),
                    ('TCK-M', 'TBOH-3', 'AGY-LEGACY', 'Medium Ticket', 'Desc M', 'Medium', 'New', '2026-11-22 12:00:00'),
                    ('TCK-L', 'TBOH-4', 'AGY-LEGACY', 'Low Ticket', 'Desc L', 'Low', 'New', '2026-11-23 12:00:00')
            """))
            conn.commit()
        eng.dispose()

        # 2. Stamp 0001_baseline_schema and upgrade to head
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        ini_path = os.path.join(root_dir, "alembic.ini")
        alembic_cfg = Config(ini_path)
        alembic_cfg.set_main_option("sqlalchemy.url", temp_db_url)

        command.stamp(alembic_cfg, "0001_baseline_schema")
        command.upgrade(alembic_cfg, "head")

        # 3. Assert weights match priorities (not all 200)
        eng_upgraded = create_db_engine(temp_db_url)
        with eng_upgraded.connect() as conn:
            rows = conn.execute(text("SELECT id, priority, priority_weight, effective_deadline_at, hotel_timezone FROM tickets ORDER BY id")).fetchall()
            weights_by_priority = {r[1]: r[2] for r in rows}

            assert weights_by_priority["Urgent"] == 1000.0, f"Expected 1000.0, got {weights_by_priority['Urgent']}"
            assert weights_by_priority["High"] == 500.0, f"Expected 500.0, got {weights_by_priority['High']}"
            assert weights_by_priority["Medium"] == 200.0, f"Expected 200.0, got {weights_by_priority['Medium']}"
            assert weights_by_priority["Low"] == 50.0, f"Expected 50.0, got {weights_by_priority['Low']}"

            # Assert not all 200
            unique_weights = set(weights_by_priority.values())
            assert len(unique_weights) == 4, f"Expected 4 distinct priority weights, got {unique_weights}"

            # Assert effective_deadline_at and hotel_timezone backfilled
            for r in rows:
                assert r[3] is not None, f"effective_deadline_at was not backfilled for ticket {r[0]}"
                assert r[4] == "UTC", f"hotel_timezone was not backfilled to UTC for ticket {r[0]}"

            # Assert users table has hashed_password column
            u_cols = conn.execute(text("PRAGMA table_info(users)")).fetchall()
            u_col_names = [c[1] for c in u_cols]
            assert "hashed_password" in u_col_names, "users table missing hashed_password after upgrade"
        eng_upgraded.dispose()

        # 4. Assert symmetric downgrade
        command.downgrade(alembic_cfg, "0001_baseline_schema")
        eng_downgraded = create_db_engine(temp_db_url)
        with eng_downgraded.connect() as conn:
            t_cols = conn.execute(text("PRAGMA table_info(tickets)")).fetchall()
            t_col_names = [c[1] for c in t_cols]
            assert "priority_weight" not in t_col_names
            assert "effective_deadline_at" not in t_col_names
            assert "hotel_timezone" not in t_col_names

            u_cols2 = conn.execute(text("PRAGMA table_info(users)")).fetchall()
            u_col_names2 = [c[1] for c in u_cols2]
            assert "hashed_password" not in u_col_names2
        eng_downgraded.dispose()

    finally:
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except Exception:
                pass


def test_alembic_postgresql_offline_sql_renders_at_time_zone_utc():
    """
    Renders offline migration SQL for postgresql dialect and asserts every
    datetime column conversion uses `AT TIME ZONE 'UTC'` on upgrade and downgrade.
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    pg_url = "postgresql+psycopg://x@localhost/x"

    # 1. Upgrade offline SQL from 0001 to 0002
    up_cmd = [
        sys.executable, "-m", "alembic",
        "-x", f"url={pg_url}",
        "upgrade", "0001_baseline_schema:0002_tz_aware_priority_weight",
        "--sql"
    ]
    up_res = subprocess.run(up_cmd, cwd=repo_root, capture_output=True, text=True, check=True)
    up_sql = up_res.stdout

    expected_cols = [
        ("tickets", "check_in_date"),
        ("tickets", "lcd_date"),
        ("tickets", "effective_deadline_at"),
        ("tickets", "created_at"),
        ("tickets", "updated_at"),
        ("events_outbox", "created_at"),
        ("events_outbox", "delivered_at"),
        ("ticket_messages", "created_at"),
        ("side_conversations", "created_at"),
        ("side_conversation_messages", "created_at"),
        ("ticket_themes", "created_at"),
        ("audit_logs", "created_at"),
        ("idempotency_records", "created_at"),
    ]

    for table, col in expected_cols:
        expected_stmt = (
            f"ALTER TABLE {table} ALTER COLUMN {col} TYPE TIMESTAMP WITH TIME ZONE "
            f"USING {col} AT TIME ZONE 'UTC';"
        )
        assert expected_stmt in up_sql, f"Missing expected upgrade SQL for {table}.{col}: {expected_stmt}"

    # 2. Downgrade offline SQL from 0002 to 0001
    down_cmd = [
        sys.executable, "-m", "alembic",
        "-x", f"url={pg_url}",
        "downgrade", "0002_tz_aware_priority_weight:0001_baseline_schema",
        "--sql"
    ]
    down_res = subprocess.run(down_cmd, cwd=repo_root, capture_output=True, text=True, check=True)
    down_sql = down_res.stdout

    for table, col in expected_cols:
        expected_down_stmt = (
            f"ALTER TABLE {table} ALTER COLUMN {col} TYPE TIMESTAMP WITHOUT TIME ZONE "
            f"USING {col} AT TIME ZONE 'UTC';"
        )
        assert expected_down_stmt in down_sql, f"Missing expected downgrade SQL for {table}.{col}: {expected_down_stmt}"


def test_alembic_postgresql_timezone_conversion_in_session_timezone():
    """
    CI test: runs ONLY when DATABASE_URL is PostgreSQL (skipped otherwise).
    Builds a legacy-shaped schema with known naive timestamps, sets session time zone
    to Asia/Kolkata, runs alembic upgrade head, and asserts check_in_date, lcd_date,
    created_at, and effective_deadline_at all equal those instants in UTC;
    then downgrades and asserts the original naive values return.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not (db_url.startswith("postgresql://") or db_url.startswith("postgresql+psycopg://")):
        pytest.skip("Test requires PostgreSQL DATABASE_URL")

    from datetime import datetime, timezone
    from alembic.config import Config
    from alembic import command
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine.url import make_url

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    ini_path = os.path.join(repo_root, "alembic.ini")

    db_name = make_url(db_url).database
    schema_name = "test_pg_tz_migration"
    raw_engine = create_engine(db_url, isolation_level="AUTOCOMMIT")
    with raw_engine.connect() as conn:
        conn.execute(text(f'ALTER DATABASE "{db_name}" SET timezone TO \'Asia/Kolkata\''))
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema_name}"))

    schema_db_url = f"{db_url}?options=-csearch_path%3D{schema_name}%2Cpublic"
    alembic_cfg = Config(ini_path)
    alembic_cfg.set_main_option("sqlalchemy.url", schema_db_url.replace("%", "%%"))
    alembic_cfg.set_main_option("version_table_schema", schema_name)

    try:
        # 1. Build legacy-shaped schema (0001_baseline_schema)
        command.upgrade(alembic_cfg, "0001_baseline_schema")

        # 2. Insert known naive timestamps into legacy schema (Asia/Kolkata session)
        schema_engine = create_engine(schema_db_url)
        known_check_in = datetime(2026, 11, 20, 10, 0, 0)
        known_lcd = datetime(2026, 11, 19, 10, 0, 0)
        known_created = datetime(2026, 11, 18, 8, 0, 0)

        with schema_engine.connect() as conn:
            conn.execute(text("SET TIME ZONE 'Asia/Kolkata'"))
            conn.execute(
                text(
                    "INSERT INTO agencies (id, name, country_code, tier) "
                    "VALUES ('AGY-TZ-1', 'TZ Test Agency', 'AE', 'standard')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO users (id, name, email, role, region, is_available, agency_id) "
                    "VALUES ('USR-TZ-1', 'TZ User', 'tz@tbo.test', 'Agent', 'MEA', true, 'AGY-TZ-1')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO tickets (id, tboh_id, agency_id, title, description, intent, priority, "
                    "status, check_in_date, lcd_date, created_at, updated_at, version) "
                    "VALUES ('TCK-TZ-1', 'TBOH-TZ-1', 'AGY-TZ-1', 'TZ Ticket', 'desc', 'Booking', 'Urgent', "
                    "'New', :cin, :lcd, :crt, :crt, 1)"
                ),
                {"cin": known_check_in, "lcd": known_lcd, "crt": known_created}
            )
            conn.commit()

        # 3. Upgrade to head (applies 0002_tz_aware_priority_weight and 0003_remove_stored_queue_score)
        command.upgrade(alembic_cfg, "head")

        # 4. Assert every datetime equals the original UTC instant
        with schema_engine.connect() as conn:
            conn.execute(text("SET TIME ZONE 'Asia/Kolkata'"))
            row = conn.execute(
                text("SELECT check_in_date, lcd_date, effective_deadline_at, created_at FROM tickets WHERE id = 'TCK-TZ-1'")
            ).fetchone()

            exp_cin = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
            exp_lcd = datetime(2026, 11, 19, 10, 0, 0, tzinfo=timezone.utc)
            exp_crt = datetime(2026, 11, 18, 8, 0, 0, tzinfo=timezone.utc)

            cin_utc = row[0].astimezone(timezone.utc) if row[0].tzinfo else row[0].replace(tzinfo=timezone.utc)
            lcd_utc = row[1].astimezone(timezone.utc) if row[1].tzinfo else row[1].replace(tzinfo=timezone.utc)
            eff_utc = row[2].astimezone(timezone.utc) if row[2].tzinfo else row[2].replace(tzinfo=timezone.utc)
            crt_utc = row[3].astimezone(timezone.utc) if row[3].tzinfo else row[3].replace(tzinfo=timezone.utc)

            assert cin_utc == exp_cin, f"Expected check_in_date {exp_cin}, got {cin_utc}"
            assert lcd_utc == exp_lcd, f"Expected lcd_date {exp_lcd}, got {lcd_utc}"
            assert eff_utc == exp_cin, f"Expected effective_deadline_at {exp_cin}, got {eff_utc}"
            assert crt_utc == exp_crt, f"Expected created_at {exp_crt}, got {crt_utc}"

        # 5. Downgrade to 0001_baseline_schema and assert original naive values come back
        command.downgrade(alembic_cfg, "0001_baseline_schema")

        with schema_engine.connect() as conn:
            conn.execute(text("SET TIME ZONE 'Asia/Kolkata'"))
            row_down = conn.execute(
                text("SELECT check_in_date, lcd_date, created_at FROM tickets WHERE id = 'TCK-TZ-1'")
            ).fetchone()

            assert (row_down[0].replace(tzinfo=None) if row_down[0].tzinfo else row_down[0]) == known_check_in
            assert (row_down[1].replace(tzinfo=None) if row_down[1].tzinfo else row_down[1]) == known_lcd
            assert (row_down[2].replace(tzinfo=None) if row_down[2].tzinfo else row_down[2]) == known_created

    finally:
        with raw_engine.connect() as conn:
            try:
                conn.execute(text(f'ALTER DATABASE "{db_name}" RESET timezone'))
            finally:
                conn.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
        raw_engine.dispose()


def test_postgresql_connection_forced_to_utc_despite_database_timezone():
    """
    PostgreSQL-only test: Verifies that database connections are forced to UTC
    even when 'ALTER DATABASE <db> SET timezone TO Asia/Kolkata' is applied.
    Ensures that tickets created with ISO Z timestamps (e.g. 2026-11-20T10:00:00Z)
    are stored and returned at UTC without session timezone shifting.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not (db_url.startswith("postgresql://") or db_url.startswith("postgresql+psycopg://")):
        pytest.skip("Test requires PostgreSQL DATABASE_URL")

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine.url import make_url
    from backend.app.database import create_db_engine

    db_name = make_url(db_url).database
    raw_engine = create_engine(db_url, isolation_level="AUTOCOMMIT")

    with raw_engine.connect() as conn:
        conn.execute(text(f'ALTER DATABASE "{db_name}" SET timezone TO \'Asia/Kolkata\''))

    try:
        app_engine = create_db_engine(db_url)
        with app_engine.connect() as conn:
            tz = conn.execute(text("SHOW timezone")).scalar()
            assert tz.upper() == "UTC", f"Expected PostgreSQL session timezone UTC, got {tz}"
        app_engine.dispose()
    finally:
        with raw_engine.connect() as conn:
            conn.execute(text(f'ALTER DATABASE "{db_name}" RESET timezone'))
        raw_engine.dispose()


def test_all_alembic_revision_ids_len_le_32():
    """Verify all Alembic revision identifiers are <= 32 characters (PostgreSQL alembic_version limit)."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    versions_dir = os.path.join(root_dir, "backend", "alembic", "versions")
    for fname in os.listdir(versions_dir):
        if fname.endswith(".py") and not fname.startswith("__"):
            mod_name = fname[:-3]
            mod = importlib.import_module(f"backend.alembic.versions.{mod_name}")
            rev = getattr(mod, "revision", None)
            assert rev is not None, f"Migration {fname} missing revision attribute"
            assert len(rev) <= 32, f"Migration revision '{rev}' in {fname} exceeds 32 chars (len={len(rev)})"


def test_alembic_migration_error_propagates_non_zero_exit():
    """
    Verify that migration errors in env.py are NOT swallowed:
    Runs a deliberately failing migration against a temp SQLite DB through
    `sys.executable -m alembic` and asserts a non-zero exit code.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    versions_dir = os.path.join(root_dir, "backend", "alembic", "versions")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db_path = f.name
    temp_db_url = f"sqlite:///{temp_db_path.replace(os.sep, '/')}"

    failing_rev_path = os.path.join(versions_dir, "9999_deliberate_failure.py")
    failing_rev_code = '''"""deliberate failure"""
from alembic import op
import sqlalchemy as sa

revision = '9999_deliberate_failure'
down_revision = '0003_remove_stored_queue_score'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Deliberately invalid SQL syntax to trigger an unhandled database error
    op.execute(sa.text("SYNTAX ERROR INVALID SQL STATEMENTS"))

def downgrade() -> None:
    pass
'''
    try:
        with open(failing_rev_path, "w", encoding="utf-8") as f:
            f.write(failing_rev_code)

        cmd = [
            sys.executable, "-m", "alembic",
            "-x", f"url={temp_db_url}",
            "upgrade", "head"
        ]
        res = subprocess.run(cmd, cwd=root_dir, capture_output=True, text=True)
        assert res.returncode != 0, f"Expected non-zero exit code on migration failure, got {res.returncode}. Output:\n{res.stdout}\n{res.stderr}"
    finally:
        if os.path.exists(failing_rev_path):
            os.remove(failing_rev_path)
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except Exception:
                pass


