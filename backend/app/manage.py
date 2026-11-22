"""OpsDesk administrative CLI management utility.

Usage:
    python -m backend.app.manage set-password --email <email> [--password <password>]
    python -m backend.app.manage create-user --email <email> --name <name> --role <role> --region <region> [--agency-id <agency_id>] [--password <password>]
"""
import argparse
import getpass
import os
import sys
import uuid
from typing import Optional

from backend.app.auth import hash_password, is_production
from backend.app.database import SessionLocal
from backend.app.models import User, Agency

DEMO_PASSWORDS = {
    "password", "demo", "demopass", "password123", "opsdesk", "test", "admin", "12345678"
}


def validate_password_strength(password: str, email: str) -> None:
    if is_production():
        if password.lower() in DEMO_PASSWORDS:
            raise ValueError(
                f"Production security violation: demo or insecure password '{password}' is prohibited in production."
            )
        if password.lower() == email.lower():
            raise ValueError(
                "Production security violation: password cannot be identical to email address."
            )
        if len(password) < 8:
            raise ValueError(
                "Production security violation: password must be at least 8 characters in production."
            )


def cmd_set_password(email: str, password: Optional[str] = None) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"Error: User with email '{email}' not found.", file=sys.stderr)
            sys.exit(1)

        if not password:
            pw1 = getpass.getpass("Enter new password: ")
            pw2 = getpass.getpass("Confirm new password: ")
            if pw1 != pw2:
                print("Error: Passwords do not match.", file=sys.stderr)
                sys.exit(1)
            password = pw1

        validate_password_strength(password, email)

        user.hashed_password = hash_password(password)
        db.commit()
        print(f"Successfully updated password for user '{user.name}' ({user.email}).")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


def cmd_create_user(
    email: str,
    name: str,
    role: str,
    region: str,
    agency_id: Optional[str] = None,
    password: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    allowed_roles = {"Requester", "Agent", "EscalationManager", "Lead"}
    if role not in allowed_roles:
        print(f"Error: Invalid role '{role}'. Allowed roles: {', '.join(sorted(allowed_roles))}", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            print(f"Error: User with email '{email}' already exists (ID: {existing.id}).", file=sys.stderr)
            sys.exit(1)

        if agency_id:
            agency = db.query(Agency).filter(Agency.id == agency_id).first()
            if not agency:
                print(f"Error: Agency with ID '{agency_id}' not found.", file=sys.stderr)
                sys.exit(1)

        if not password:
            pw1 = getpass.getpass("Enter password for new user: ")
            pw2 = getpass.getpass("Confirm password: ")
            if pw1 != pw2:
                print("Error: Passwords do not match.", file=sys.stderr)
                sys.exit(1)
            password = pw1

        validate_password_strength(password, email)

        uid = user_id or f"USR-{uuid.uuid4().hex[:6].upper()}"
        new_user = User(
            id=uid,
            email=email,
            name=name,
            role=role,
            region=region,
            agency_id=agency_id,
            is_available=True,
            hashed_password=hash_password(password),
        )
        db.add(new_user)
        db.commit()
        print(f"Successfully created user '{new_user.name}' ({new_user.email}) with ID '{new_user.id}'.")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


def cmd_refresh_scores(batch_size: int = 500) -> None:
    """Refreshes stale ticket queue scores in batches."""
    from backend.services.routing_engine import refresh_stale_queue_scores
    db = SessionLocal()
    try:
        count = refresh_stale_queue_scores(db, batch_size=batch_size)
        print(f"Successfully refreshed {count} ticket queue scores.")
    except Exception as e:
        print(f"Error during refresh-scores: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m backend.app.manage", description="OpsDesk Management CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # set-password
    p_setpw = subparsers.add_parser("set-password", help="Set or reset a user's password")
    p_setpw.add_argument("--email", required=True, help="User email address")
    p_setpw.add_argument("--password", required=False, help="New password (prompts if omitted)")

    # create-user
    p_create = subparsers.add_parser("create-user", help="Create a new system user")
    p_create.add_argument("--email", required=True, help="User email address")
    p_create.add_argument("--name", required=True, help="Full display name")
    p_create.add_argument("--role", required=True, choices=["Requester", "Agent", "EscalationManager", "Lead"], help="User role")
    p_create.add_argument("--region", required=True, help="User region (e.g. MEA, APAC, EUR)")
    p_create.add_argument("--agency-id", required=False, help="Associated Agency ID (required for Requester)")
    p_create.add_argument("--password", required=False, help="User password (prompts if omitted)")
    p_create.add_argument("--user-id", required=False, help="Optional explicit user ID")

    # refresh-scores
    p_refresh = subparsers.add_parser("refresh-scores", help="Refresh stale ticket queue scores")
    p_refresh.add_argument("--batch-size", type=int, default=500, help="Batch size for refresh updates (default: 500)")

    args = parser.parse_args(argv)

    if args.command == "set-password":
        cmd_set_password(email=args.email, password=args.password)
    elif args.command == "create-user":
        cmd_create_user(
            email=args.email,
            name=args.name,
            role=args.role,
            region=args.region,
            agency_id=args.agency_id,
            password=args.password,
            user_id=args.user_id,
        )
    elif args.command == "refresh-scores":
        cmd_refresh_scores(batch_size=args.batch_size)


if __name__ == "__main__":
    main()
