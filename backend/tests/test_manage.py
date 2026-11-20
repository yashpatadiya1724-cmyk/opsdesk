import pytest
from sqlalchemy.orm import Session

from backend.app.auth import verify_password
from backend.app.models import User, Agency
from backend.app import manage


def test_manage_set_password_successful(db_session: Session, monkeypatch):
    agency = Agency(id="AGY-MANAGE-1", name="Manage Agency", country_code="IN", tier="standard")
    user = User(
        id="USR-MANAGE-1",
        email="test_manage@opsdesk.com",
        name="Manage User",
        role="Agent",
        region="APAC",
        agency_id=agency.id,
        hashed_password=None,
    )
    db_session.add(agency)
    db_session.add(user)
    db_session.commit()

    # Monkeypatch SessionLocal in manage module to use test session factory
    monkeypatch.setattr(manage, "SessionLocal", lambda: db_session)

    manage.cmd_set_password(email="test_manage@opsdesk.com", password="SecureValidPassword123!")

    updated_user = db_session.query(User).filter(User.id == "USR-MANAGE-1").first()
    assert updated_user.hashed_password is not None
    assert verify_password("SecureValidPassword123!", updated_user.hashed_password)


def test_manage_set_password_refuses_demo_password_in_production(db_session: Session, monkeypatch):
    user = User(
        id="USR-MANAGE-2",
        email="prod_user@opsdesk.com",
        name="Prod User",
        role="Agent",
        region="APAC",
        hashed_password=None,
    )
    db_session.add(user)
    db_session.commit()

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(manage, "SessionLocal", lambda: db_session)

    # In production, demo passwords must exit with error
    with pytest.raises(SystemExit) as exc:
        manage.cmd_set_password(email="prod_user@opsdesk.com", password="password")
    assert exc.value.code == 1

    # Short password (<8 chars)
    with pytest.raises(SystemExit) as exc2:
        manage.cmd_set_password(email="prod_user@opsdesk.com", password="abc")
    assert exc2.value.code == 1

    # Password == email
    with pytest.raises(SystemExit) as exc3:
        manage.cmd_set_password(email="prod_user@opsdesk.com", password="prod_user@opsdesk.com")
    assert exc3.value.code == 1


def test_manage_create_user_successful(db_session: Session, monkeypatch):
    monkeypatch.setattr(manage, "SessionLocal", lambda: db_session)

    manage.cmd_create_user(
        email="new_agent@opsdesk.com",
        name="New Agent",
        role="Agent",
        region="EUR",
        password="ValidPassword789!",
        user_id="USR-NEW-001"
    )

    created = db_session.query(User).filter(User.email == "new_agent@opsdesk.com").first()
    assert created is not None
    assert created.name == "New Agent"
    assert created.role == "Agent"
    assert verify_password("ValidPassword789!", created.hashed_password)


def test_manage_create_user_duplicate_email_fails(db_session: Session, monkeypatch):
    user = User(
        id="USR-EXISTING",
        email="existing@opsdesk.com",
        name="Existing User",
        role="Agent",
        region="MEA",
    )
    db_session.add(user)
    db_session.commit()

    monkeypatch.setattr(manage, "SessionLocal", lambda: db_session)

    with pytest.raises(SystemExit) as exc:
        manage.cmd_create_user(
            email="existing@opsdesk.com",
            name="Duplicate User",
            role="Agent",
            region="MEA",
            password="SomePassword123!"
        )
    assert exc.value.code == 1
