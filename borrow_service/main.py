"""FastAPI borrow service / FastAPI 借阅服务。"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from py_eureka_client.eureka_client import EurekaClient

from .clients import (
    BOOK_SERVICE,
    USER_SERVICE,
    EurekaServiceResolver,
    LibraryServiceClient,
    ServiceCallError,
)
from .database import init_db
from .models import (
    cancel_return,
    claim_return,
    complete_return,
    create_borrow,
    list_user_borrows,
)
from .schemas import BorrowCreate, BorrowResponse, HealthResponse


SERVICE_NAME = "borrow-service"
DEFAULT_SERVICE_PORT = 8003
logger = logging.getLogger(__name__)


def get_service_port() -> int:
    """Read the instance port / 读取实例端口。"""
    value = int(os.getenv("SERVICE_PORT", str(DEFAULT_SERVICE_PORT)))
    if not 1 <= value <= 65535:
        raise RuntimeError("SERVICE_PORT must be between 1 and 65535")
    return value


def read_positive_int(name: str, default: int) -> int:
    """Read a positive integer setting / 读取正整数配置。"""
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise RuntimeError(f"{name} must be positive")
    return value


def read_positive_float(name: str, default: float) -> float:
    """Read a positive float setting / 读取正浮点配置。"""
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


async def start_eureka_client() -> EurekaClient | None:
    """Register and start registry discovery / 注册并启动服务发现。"""
    eureka_server = os.getenv("EUREKA_SERVER")
    if not eureka_server:
        logger.info("EUREKA_SERVER is not set; downstream discovery is unavailable")
        return None

    client = EurekaClient(
        eureka_server=eureka_server,
        app_name=SERVICE_NAME,
        instance_port=get_service_port(),
        should_register=True,
        should_discover=True,
    )
    await client.start()
    return client


def create_library_client(eureka_client: EurekaClient | None) -> LibraryServiceClient:
    """Create the discovered service client / 创建基于发现的服务客户端。"""
    return LibraryServiceClient(
        resolver=EurekaServiceResolver(eureka_client),
        timeout_seconds=read_positive_float("DOWNSTREAM_TIMEOUT_SECONDS", 2.0),
        failure_threshold=read_positive_int("CIRCUIT_BREAKER_FAILURE_THRESHOLD", 3),
        recovery_timeout_seconds=read_positive_float("CIRCUIT_BREAKER_RECOVERY_SECONDS", 5.0),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage database, HTTP, and Eureka resources / 管理数据库、HTTP 与 Eureka 资源。"""
    init_db()
    eureka_client = None
    try:
        eureka_client = await start_eureka_client()
    except Exception:
        logger.exception("Unable to initialize Eureka discovery")

    service_client = create_library_client(eureka_client)
    app.state.eureka_client = eureka_client
    app.state.service_client = service_client
    try:
        yield
    finally:
        await service_client.close()
        if eureka_client is not None:
            try:
                await eureka_client.stop()
            except Exception:
                logger.exception("Unable to unregister %s", SERVICE_NAME)


app = FastAPI(title="Library Borrow Service", lifespan=lifespan)


def require_user_id(
    user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> str:
    """Require the Gateway-provided user ID / 要求 Gateway 提供用户 ID。"""
    if user_id is None or not user_id.strip():
        raise HTTPException(status_code=401, detail="X-User-Id header is required")
    return user_id.strip()


def get_service_client(request: Request) -> LibraryServiceClient:
    """Return the application service client / 返回应用服务客户端。"""
    return request.app.state.service_client


def raise_service_error(error: ServiceCallError) -> None:
    """Translate a downstream error to HTTP / 将下游错误转换为 HTTP 响应。"""
    headers = None
    if error.retry_after_seconds is not None:
        headers = {"Retry-After": str(error.retry_after_seconds)}
    raise HTTPException(status_code=error.status_code, detail=error.detail(), headers=headers)


@app.post("/api/borrows", response_model=BorrowResponse, status_code=status.HTTP_201_CREATED)
@app.post("/borrows", response_model=BorrowResponse, status_code=status.HTTP_201_CREATED)
async def borrow_book(
    payload: BorrowCreate,
    user_id: Annotated[str, Depends(require_user_id)],
    service_client: Annotated[LibraryServiceClient, Depends(get_service_client)],
    authorization: Annotated[str | None, Header()] = None,
) -> BorrowResponse:
    """Validate remote entities and borrow a book / 验证远程实体并借书。"""
    try:
        await service_client.validate_user(user_id, authorization)
        _, selected_book_url = await service_client.get_book(payload.book_id)
        await service_client.borrow_book(payload.book_id, selected_book_url)
    except ServiceCallError as error:
        raise_service_error(error)

    try:
        record = create_borrow(user_id, payload.book_id)
    except Exception:
        logger.exception("Unable to persist borrow; compensating book inventory")
        try:
            await service_client.return_book(payload.book_id, selected_book_url)
        except ServiceCallError:
            logger.exception("Inventory compensation failed for book_id=%s", payload.book_id)
        raise HTTPException(status_code=500, detail="Borrow could not be persisted")
    return BorrowResponse.model_validate(record)


@app.get("/api/borrows/me", response_model=list[BorrowResponse])
@app.get("/borrows/me", response_model=list[BorrowResponse])
def my_borrows(user_id: Annotated[str, Depends(require_user_id)]) -> list[BorrowResponse]:
    """List the current user's records / 列出当前用户的借阅记录。"""
    return [BorrowResponse.model_validate(record) for record in list_user_borrows(user_id)]


@app.post("/api/borrows/{borrow_id}/return", response_model=BorrowResponse)
@app.post("/borrows/{borrow_id}/return", response_model=BorrowResponse)
async def return_borrow(
    borrow_id: int,
    user_id: Annotated[str, Depends(require_user_id)],
    service_client: Annotated[LibraryServiceClient, Depends(get_service_client)],
) -> BorrowResponse:
    """Return a borrowed book exactly once / 仅归还一次已借图书。"""
    record, claimed = claim_return(borrow_id, user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Borrow record not found")
    if not claimed:
        raise HTTPException(status_code=409, detail="Borrow record is already returned or returning")

    try:
        await service_client.return_book(record.book_id)
    except ServiceCallError as error:
        cancel_return(borrow_id, user_id)
        raise_service_error(error)
    return BorrowResponse.model_validate(complete_return(borrow_id, user_id))


@app.get("/health", response_model=HealthResponse)
def health(
    service_client: Annotated[LibraryServiceClient, Depends(get_service_client)],
) -> HealthResponse:
    """Report service and breaker health / 返回服务及熔断器状态。"""
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        port=get_service_port(),
        breakers={
            USER_SERVICE: service_client.breaker_state(USER_SERVICE),
            BOOK_SERVICE: service_client.breaker_state(BOOK_SERVICE),
        },
    )
