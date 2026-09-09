"""Password and JWT helpers / 密码与 JWT 辅助函数。"""

import base64
import binascii
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt


PASSWORD_SCHEME = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 16
DERIVED_KEY_BYTES = 32
JWT_ALGORITHM = "HS256"
DEFAULT_TOKEN_MINUTES = 60
MINIMUM_JWT_SECRET_BYTES = 32


def encode_bytes(value: bytes) -> str:
    """Encode bytes for text storage / 将字节编码为可存储文本。"""
    return base64.urlsafe_b64encode(value).decode("ascii")


def decode_bytes(value: str) -> bytes:
    """Decode stored text into bytes / 将存储文本解码为字节。"""
    return base64.b64decode(value, altchars=b"-_", validate=True)


def hash_password(password: str) -> str:
    """Hash a password with a unique salt / 使用独立盐值哈希密码。"""
    salt = secrets.token_bytes(SALT_BYTES)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=DERIVED_KEY_BYTES,
    )
    return "$".join(
        (
            PASSWORD_SCHEME,
            str(PBKDF2_ITERATIONS),
            encode_bytes(salt),
            encode_bytes(derived_key),
        )
    )


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password safely / 安全验证密码。"""
    try:
        scheme, iterations_text, salt_text, expected_text = stored_hash.split("$")
        if scheme != PASSWORD_SCHEME:
            return False

        iterations = int(iterations_text)
        if iterations <= 0:
            return False

        salt = decode_bytes(salt_text)
        expected_key = decode_bytes(expected_text)
        candidate_key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
            dklen=len(expected_key),
        )
    except (ValueError, TypeError, binascii.Error):
        return False

    return hmac.compare_digest(candidate_key, expected_key)


def get_jwt_secret() -> str:
    """Read the JWT secret from the environment / 从环境变量读取 JWT 密钥。"""
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET environment variable is required")
    if len(secret.encode("utf-8")) < MINIMUM_JWT_SECRET_BYTES:
        raise RuntimeError("JWT_SECRET must contain at least 32 bytes")
    return secret


def get_token_ttl_seconds() -> int:
    """Read and validate token lifetime / 读取并校验令牌有效期。"""
    minutes_text = os.getenv("JWT_EXPIRE_MINUTES", str(DEFAULT_TOKEN_MINUTES))
    try:
        minutes = int(minutes_text)
    except ValueError as error:
        raise RuntimeError("JWT_EXPIRE_MINUTES must be an integer") from error
    if minutes <= 0:
        raise RuntimeError("JWT_EXPIRE_MINUTES must be positive")
    return minutes * 60


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    """Create a signed JWT / 创建签名 JWT。"""
    ttl_seconds = get_token_ttl_seconds()
    issued_at = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=ttl_seconds),
    }
    token = jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)
    return token, ttl_seconds


def decode_access_token(token: str) -> dict[str, object]:
    """Verify and decode a JWT / 校验并解码 JWT。"""
    payload = jwt.decode(
        token,
        get_jwt_secret(),
        algorithms=[JWT_ALGORITHM],
        options={"require": ["sub", "role", "iat", "exp"]},
    )

    subject = payload.get("sub")
    role = payload.get("role")
    if not isinstance(subject, str) or not subject.isdigit():
        raise jwt.InvalidTokenError("JWT subject must be a numeric string")
    if not isinstance(role, str) or not role:
        raise jwt.InvalidTokenError("JWT role must be a non-empty string")
    return payload
