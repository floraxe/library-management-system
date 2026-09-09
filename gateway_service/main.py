"""FastAPI API gateway / FastAPI API 网关。"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from py_eureka_client.eureka_client import EurekaClient

from .auth_filter import jwt_auth_filter
from .routes import forward_request


SERVICE_NAME = "gateway-service"
SERVICE_PORT = 8011
PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
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
    """Manage the Eureka lifecycle / 管理 Eureka 生命周期。"""
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


app = FastAPI(title="Library API Gateway", lifespan=lifespan)
app.middleware("http")(jwt_auth_filter)


@app.post("/auth/register")
async def proxy_register(request: Request) -> Response:
    """Forward public registration / 转发公开注册请求。"""
    return await forward_request(request, "USER_SERVICE_URL", include_identity=False)


@app.post("/auth/login")
async def proxy_login(request: Request) -> Response:
    """Forward public login / 转发公开登录请求。"""
    return await forward_request(request, "USER_SERVICE_URL", include_identity=False)


@app.get("/users/{user_id}")
async def proxy_user(request: Request, user_id: int) -> Response:
    """Forward an authenticated user query / 转发已认证用户查询。"""
    return await forward_request(request, "USER_SERVICE_URL", include_identity=True)


@app.api_route("/api/books", methods=PROXY_METHODS)
async def proxy_books_root(request: Request) -> Response:
    """Forward the books collection path / 转发图书集合路径。"""
    return await forward_request(request, "BOOK_SERVICE_URL", include_identity=True)


@app.api_route("/api/books/{remaining_path:path}", methods=PROXY_METHODS)
async def proxy_books_path(request: Request, remaining_path: str) -> Response:
    """Forward a nested books path / 转发图书子路径。"""
    return await forward_request(request, "BOOK_SERVICE_URL", include_identity=True)


@app.api_route("/api/borrows", methods=PROXY_METHODS)
async def proxy_borrows_root(request: Request) -> Response:
    """Forward the borrows collection path / 转发借阅集合路径。"""
    return await forward_request(request, "BORROW_SERVICE_URL", include_identity=True)


@app.api_route("/api/borrows/{remaining_path:path}", methods=PROXY_METHODS)
async def proxy_borrows_path(request: Request, remaining_path: str) -> Response:
    """Forward a nested borrows path / 转发借阅子路径。"""
    return await forward_request(request, "BORROW_SERVICE_URL", include_identity=True)


@app.get("/health")
def health() -> dict[str, str]:
    """Report Gateway health / 返回 Gateway 健康状态。"""
    return {"status": "ok", "service": SERVICE_NAME}
