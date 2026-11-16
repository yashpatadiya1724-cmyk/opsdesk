import os
import uuid
import sqlite3
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import get_db
from backend.app.main import app
from backend.seed.seed_data import seed_database

# Path to the development database in project root (overridable via OPSDESK_DEV_DB env var)
DEV_DB_PATH = os.environ.get(
    "OPSDESK_DEV_DB",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "opsdesk.db"
    )
)

@pytest.fixture(scope="session")
def dev_db_initial_state():
    """
    Records initial state (mtime and row count) of opsdesk.db before test execution.
    Used to guarantee dev database is 100% isolated and never modified by tests.
    """
    if not os.path.exists(DEV_DB_PATH):
        pytest.skip(f"Development database not found at {DEV_DB_PATH}; skipping dev DB isolation check in isolated worktree")
    initial_mtime = os.path.getmtime(DEV_DB_PATH)
    conn = sqlite3.connect(DEV_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tickets")
    initial_count = cur.fetchone()[0]
    conn.close()
    return {"path": DEV_DB_PATH, "mtime": initial_mtime, "count": initial_count}


@pytest.fixture(scope="session")
def test_db_setup():
    """
    Creates an isolated temporary SQLite database for tests.
    Guarantees dev opsdesk.db is NEVER touched, cleared, or altered by test suite.
    """
    temp_dir = tempfile.gettempdir()
    db_file = os.path.join(temp_dir, f"test_opsdesk_{uuid.uuid4().hex[:8]}.db")
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSessionLocal()
    seed_database(session, engine_bind=engine, total_tickets=5000)
    session.close()

    yield engine, TestSessionLocal

    engine.dispose()
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass


@pytest.fixture(scope="function")
def db_session(test_db_setup):
    """Provides a transactional session on the isolated test database."""
    _, TestSessionLocal = test_db_setup
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session")
def client(test_db_setup):
    """Configures FastAPI TestClient overriding get_db with the isolated test DB."""
    _, TestSessionLocal = test_db_setup

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
