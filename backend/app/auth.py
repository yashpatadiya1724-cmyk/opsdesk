import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import hashlib
import hmac
import bcrypt
import jwt
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.models import User

logger = logging.getLogger("opsdesk.auth")

DEFAULT_AUTH_MODE = "demo"
DEFAULT_JWT_ALGORITHM = "HS256"
DEFAULT_JWT_EXPIRE_MINUTES = 480
DEFAULT_JWT_SECRET = "opsdesk-jwt-default-insecure-secret-key-change-in-production"
DEFAULT_BCRYPT_ROUNDS = 12
ALLOWED_JWT_ALGORITHMS = {"HS256", "HS384", "HS512"}


def is_production() -> bool:
    """
    Returns True if APP_ENV, ENVIRONMENT, or ENV equals 'production' or 'prod' (case-insensitive).
    """
    for var in ("APP_ENV", "ENVIRONMENT", "ENV"):
        val = os.environ.get(var)
        if val is not None and val.strip().lower() in ("production", "prod"):
            return True
    return False


def get_bcrypt_rounds() -> int:
    """
    Returns configured bcrypt rounds from BCRYPT_ROUNDS environment variable,
    falling back to DEFAULT_BCRYPT_ROUNDS (12).
    Refuses BCRYPT_ROUNDS < 10 in production.
    """
    raw = os.environ.get("BCRYPT_ROUNDS")
    if raw is not None:
        try:
            val = int(raw)
        except (ValueError, TypeError):
            val = DEFAULT_BCRYPT_ROUNDS
    else:
        val = DEFAULT_BCRYPT_ROUNDS

    if is_production() and val < 10:
        raise ValueError(
            f"Insecure BCRYPT_ROUNDS={val} is refused in production (must be >= 10)."
        )
    return max(4, min(31, val))


def hash_password(password: str, rounds: Optional[int] = None) -> str:
    """
    Hashes a password using bcrypt with a generated salt.
    Rounds are configurable via BCRYPT_ROUNDS (default 12; test suites set 4).
    """
    if not isinstance(password, str):
        password = str(password)
    pw_bytes = password.encode("utf-8")
    if rounds is None:
        rounds = get_bcrypt_rounds()
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """
    Verifies a plain password against the hashed password.
    Supports bcrypt ($2b$, $2a$, $2y$) and legacy PBKDF2-SHA256 for backward compatibility.
    """
    if not hashed or not password:
        return False
    try:
        pw_bytes = password.encode("utf-8")
        if hashed.startswith("$2b$") or hashed.startswith("$2a$") or hashed.startswith("$2y$"):
            return bcrypt.checkpw(pw_bytes, hashed.encode("utf-8"))
        elif hashed.startswith("pbkdf2_sha256$"):
            parts = hashed.split("$")
            if len(parts) == 4:
                iterations = int(parts[1])
                salt = bytes.fromhex(parts[2])
                expected_hash = parts[3]
                dk = hashlib.pbkdf2_hmac("sha256", pw_bytes, salt, iterations)
                return hmac.compare_digest(dk.hex(), expected_hash)
        return False
    except Exception as exc:
        logger.warning(f"Password verification error: {exc}")
        return False


def get_active_jwt_secret() -> str:
    """
    Resolves the active JWT secret key:
    In AUTH_MODE=jwt, strictly refuses default insecure secret or secrets < 32 characters.
    """
    auth_mode = os.environ.get("AUTH_MODE", DEFAULT_AUTH_MODE).lower()
    secret = os.environ.get("JWT_SECRET", "")
    if auth_mode == "jwt":
        if not secret or len(secret.strip()) < 32 or secret == DEFAULT_JWT_SECRET:
            raise HTTPException(
                status_code=500,
                detail="Server configuration error: In AUTH_MODE=jwt, JWT_SECRET must be explicitly configured and cannot be empty, shorter than 32 characters, or equal to DEFAULT_JWT_SECRET."
            )
        return secret
    return secret or DEFAULT_JWT_SECRET


def get_active_jwt_algorithm() -> str:
    """
    Resolves and verifies active JWT algorithm against whitelist (HS256, HS384, HS512).
    """
    algorithm = os.environ.get("JWT_ALGORITHM", DEFAULT_JWT_ALGORITHM)
    if algorithm not in ALLOWED_JWT_ALGORITHMS:
        raise HTTPException(
            status_code=500,
            detail=f"Server configuration error: Unsupported JWT_ALGORITHM '{algorithm}'. Allowed algorithms: {', '.join(sorted(ALLOWED_JWT_ALGORITHMS))}."
        )
    return algorithm


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Encodes a JWT using PyJWT.
    """
    to_encode = data.copy()
    now_utc = datetime.now(timezone.utc)
    if expires_delta is not None:
        expire = now_utc + expires_delta
    else:
        try:
            expire_minutes = int(os.environ.get("JWT_EXPIRE_MINUTES", str(DEFAULT_JWT_EXPIRE_MINUTES)))
        except ValueError:
            expire_minutes = DEFAULT_JWT_EXPIRE_MINUTES
        expire = now_utc + timedelta(minutes=expire_minutes)

    to_encode.update({
        "exp": expire,
        "iat": now_utc,
    })

    secret = get_active_jwt_secret()
    algorithm = get_active_jwt_algorithm()
    return jwt.encode(to_encode, secret, algorithm=algorithm)


def decode_access_token(token: str) -> dict:
    """
    Decodes and verifies a JWT using PyJWT.
    Enforces required claims: exp and sub via PyJWT options={'require': ['exp', 'sub']}.
    Raises HTTPException(401) on invalid signature, expired token, missing claims, or malformed token.
    """
    if not token or not isinstance(token, str):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid token format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    secret = get_active_jwt_secret()
    algorithm = get_active_jwt_algorithm()

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            options={"require": ["exp", "sub"]}
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.MissingRequiredClaimError as exc:
        raise HTTPException(
            status_code=401,
            detail=f"Unauthorized: Missing required token claim ({exc})",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidAlgorithmError as exc:
        raise HTTPException(
            status_code=401,
            detail=f"Unauthorized: Unsupported algorithm '{exc}'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid or tampered token signature",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Could not decode token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    db: Session = Depends(get_db)
) -> User:
    """
    Authenticates requests using:
    - AUTH_MODE=jwt: Requires 'Authorization: Bearer <token>' header.
    - AUTH_MODE=demo: Primary mechanism is 'X-User-Id' header, with fallback acceptance of valid Bearer token.
    Raises 401 Unauthorized if missing, expired, tampered, or invalid.
    """
    auth_mode = os.environ.get("AUTH_MODE", DEFAULT_AUTH_MODE).lower()

    if auth_mode == "jwt":
        if not authorization:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: Missing Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )
        parts = authorization.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: Invalid authentication scheme, expected Bearer <token>",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = parts[1].strip()
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: Token missing subject identifier",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=401,
                detail=f"Unauthorized: User '{user_id}' not found in system",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user

    else:
        # demo mode
        if x_user_id:
            user = db.query(User).filter(User.id == x_user_id).first()
            if not user:
                raise HTTPException(
                    status_code=401,
                    detail=f"Unauthorized: User '{x_user_id}' not found in system"
                )
            return user
        elif authorization:
            parts = authorization.split(" ", 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                token = parts[1].strip()
                payload = decode_access_token(token)
                user_id = payload.get("sub")
                if not user_id:
                    raise HTTPException(
                        status_code=401,
                        detail="Unauthorized: Token missing subject identifier",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    raise HTTPException(
                        status_code=401,
                        detail=f"Unauthorized: User '{user_id}' not found in system",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                return user

        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Missing X-User-Id authentication header"
        )
