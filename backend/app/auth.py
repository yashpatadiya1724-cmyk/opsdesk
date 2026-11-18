import os
import json
import hmac
import base64
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.models import User

DEFAULT_AUTH_MODE = "demo"
DEFAULT_JWT_ALGORITHM = "HS256"
DEFAULT_JWT_EXPIRE_MINUTES = 480
DEFAULT_JWT_SECRET = "opsdesk-jwt-default-insecure-secret-key-change-in-production"


def hash_password(password: str) -> str:
    """
    Hashes a password using PBKDF2-HMAC-SHA256 with 100,000 iterations and a random salt.
    Format: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
    """
    if not isinstance(password, str):
        password = str(password)
    salt = secrets.token_hex(16)
    iterations = 100000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """
    Verifies a plain password against the hashed password.
    Returns True if valid, False otherwise.
    """
    if not hashed or not password:
        return False
    parts = hashed.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    try:
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected_hash = parts[3]
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(dk.hex(), expected_hash)
    except Exception:
        return False


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _base64url_decode(data: str) -> bytes:
    padding = len(data) % 4
    if padding:
        data += "=" * (4 - padding)
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Encodes a JWT using pure-Python HS256 algorithm.
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
        "exp": int(expire.timestamp()),
        "iat": int(now_utc.timestamp()),
    })

    algorithm = os.environ.get("JWT_ALGORITHM", DEFAULT_JWT_ALGORITHM)
    header = {"alg": algorithm, "typ": "JWT"}

    header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_bytes = json.dumps(to_encode, separators=(",", ":"), sort_keys=True).encode("utf-8")

    header_b64 = _base64url_encode(header_bytes)
    payload_b64 = _base64url_encode(payload_bytes)

    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    secret = os.environ.get("JWT_SECRET", DEFAULT_JWT_SECRET).encode("utf-8")
    signature = hmac.new(secret, signing_input, hashlib.sha256).digest()
    sig_b64 = _base64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_access_token(token: str) -> dict:
    """
    Decodes and verifies a HS256 JWT using pure-Python.
    Raises HTTPException(401) on invalid signature, expired token, or malformed token.
    """
    if not token or not isinstance(token, str):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid token format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid token format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    header_b64, payload_b64, sig_b64 = parts
    secret = os.environ.get("JWT_SECRET", DEFAULT_JWT_SECRET).encode("utf-8")
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected_sig = hmac.new(secret, signing_input, hashlib.sha256).digest()

    try:
        actual_sig = _base64url_decode(sig_b64)
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid token encoding",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid or tampered token signature",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        header_bytes = _base64url_decode(header_b64)
        header = json.loads(header_bytes.decode("utf-8"))
        algorithm = os.environ.get("JWT_ALGORITHM", DEFAULT_JWT_ALGORITHM)
        if header.get("alg") != algorithm:
            raise HTTPException(
                status_code=401,
                detail=f"Unauthorized: Unsupported algorithm '{header.get('alg')}'",
                headers={"WWW-Authenticate": "Bearer"},
            )

        payload_bytes = _base64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Could not decode token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    exp = payload.get("exp")
    if exp is not None:
        now_ts = datetime.now(timezone.utc).timestamp()
        if now_ts > exp:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return payload


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
