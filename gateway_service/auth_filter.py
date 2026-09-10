"""Gateway JWT authentication filter / Gateway JWT 鉴权过滤器。"""

import os
from dataclasses import dataclass

import jwt
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint


JWT_ALGORITHM = "HS256"
MINIMUM_JWT_SECRET_BYTES = 32
PUBLIC_PATHS = {
    "/auth/register",
    "/auth/login",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}


@dataclass(frozen=True)
class AuthenticatedUser:
    """Hold verified identity claims / 保存已验签身份声明。"""

    user_id: str
    role: str


def get_jwt_secret() -> str:
    """Read the shared secret from the environment / 从环境变量读取共享密钥。"""
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET environment variable is required")
    if len(secret.encode("utf-8")) < MINIMUM_JWT_SECRET_BYTES:
        raise RuntimeError("JWT_SECRET must contain at least 32 bytes")
    return secret


def authenticate_header(authorization: str | None) -> AuthenticatedUser:
    """Validate Bearer credentials / 校验 Bearer 凭据。"""
    if not authorization:
        raise jwt.InvalidTokenError("Authorization header is missing")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise jwt.InvalidTokenError("Authorization header must use Bearer authentication")

    payload = jwt.decode(
        parts[1],
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
    return AuthenticatedUser(user_id=subject, role=role)


def unauthorized_response() -> JSONResponse:
    """Build a consistent 401 response / 构造统一的 401 响应。"""
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": "Invalid or missing access token"},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def jwt_auth_filter(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    """Protect every non-public request / 保护所有非公开请求。"""
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    try:
        request.state.user = authenticate_header(request.headers.get("Authorization"))
    except jwt.InvalidTokenError:
        return unauthorized_response()
    return await call_next(request)