"""FastAPI user service / FastAPI 用户服务。"""

import logging
import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Path, status
from py_eureka_client.eureka_client import EurekaClient

from .auth import create_access_token, decode_access_token, hash_password, verify_password
from .database import init_db
from .models import create_user, get_user_by_email, get_user_by_id, get_user_by_username
from .schemas import HealthResponse, LoginRequest, RegisterRequest, TokenResponse, UserResponse


SERVICE_NAME = "user-service"
SERVICE_PORT = 8012
logger = logging.getLogger(__name__)


async def start_eureka_client() -> EurekaClient | None:
    """Register when Eureka is configured / 配置 Eureka 后注册服务。"""
    eureka_server = os.getenv("EUREKA_SERVER")
    if not eureka_server:
        logger.info("EUREKA_SERVER is not set; skipping service registration")
        return None

    client = EurekaClient(
        eureka_server=eureka_server,
        app_name=SERVICE_NAME,
        instance_port=SERVICE_PORT,
        should_discover=False,
    )
    await client.start()
    logger.info("Registered %s:%s with Eureka", SERVICE_NAME, SERVICE_PORT)
    return client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage database and Eureka lifecycle / 管理数据库及 Eureka 生命周期。"""
    init_db()
    client = None
    try:
        client = await start_eureka_client()
    except Exception:
        logger.exception("Unable to register %s with Eureka", SERVICE_NAME)

    app.state.eureka_client = client
    try:
        yield
    finally:
        if client is not None:
            try:
                await client.stop()
                logger.info("Unregistered %s from Eureka", SERVICE_NAME)
            except Exception:
                logger.exception("Unable to unregister %s from Eureka", SERVICE_NAME)


app = FastAPI(title="Library User Service", lifespan=lifespan)


def unauthorized(detail: str = "Invalid or missing access token") -> HTTPException:
    """Build a consistent authentication error / 构造统一鉴权错误。"""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_access_token(
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    """Validate a Bearer token / 校验 Bearer Token。"""
    if not authorization:
        raise unauthorized()

    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token or " " in token:
        raise unauthorized()

    try:
        return decode_access_token(token)
    except jwt.InvalidTokenError as error:
        raise unauthorized() from error


@app.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: RegisterRequest) -> UserResponse:
    """Register a normal user / 注册普通用户。"""
    if get_user_by_username(payload.username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    if get_user_by_email(payload.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    try:
        user = create_user(
            username=payload.username,
            email=payload.email,
            password_hash=hash_password(payload.password),
        )
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already exists",
        ) from error
    return UserResponse.model_validate(user)


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    """Verify credentials and issue a JWT / 验证凭据并签发 JWT。"""
    user = get_user_by_username(payload.username)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise unauthorized("Invalid username or password")

    token, ttl_seconds = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, expires_in=ttl_seconds)


@app.get("/users/{user_id}", response_model=UserResponse)
def get_user(
    user_id: Annotated[int, Path(gt=0)],
    _claims: Annotated[dict[str, object], Depends(require_access_token)],
) -> UserResponse:
    """Return one user to an authenticated caller / 向已认证调用方返回用户。"""
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.model_validate(user)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report service health / 返回服务健康状态。"""
    return HealthResponse(status="ok", service=SERVICE_NAME)
