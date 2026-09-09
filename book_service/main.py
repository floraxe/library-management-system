"""FastAPI book service / FastAPI 图书服务。"""

import logging
import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Response, status
from py_eureka_client.eureka_client import EurekaClient

from .database import init_db
from .models import (
    BookHasActiveLoansError,
    InventoryLimitError,
    InventoryUnavailableError,
    TotalBelowBorrowedError,
    borrow_copy,
    create_book,
    delete_book,
    get_book,
    return_copy,
    search_books,
    update_book,
)
from .schemas import BookCreate, BookResponse, BookUpdate, HealthResponse, InventoryResponse


SERVICE_NAME = "book-service"
DEFAULT_SERVICE_PORT = 8002
logger = logging.getLogger(__name__)


def get_service_port() -> int:
    """Read the instance port / 读取实例端口。"""
    value = int(os.getenv("SERVICE_PORT", str(DEFAULT_SERVICE_PORT)))
    if not 1 <= value <= 65535:
        raise RuntimeError("SERVICE_PORT must be between 1 and 65535")
    return value


def get_instance_id() -> str:
    """Read a log-friendly instance ID / 读取便于记录的实例标识。"""
    return os.getenv("INSTANCE_ID", f"{SERVICE_NAME}-{get_service_port()}")


async def start_eureka_client() -> EurekaClient | None:
    """Register this book instance / 注册当前图书实例。"""
    eureka_server = os.getenv("EUREKA_SERVER")
    if not eureka_server:
        logger.info("EUREKA_SERVER is not set; skipping service registration")
        return None

    client = EurekaClient(
        eureka_server=eureka_server,
        app_name=SERVICE_NAME,
        instance_id=get_instance_id(),
        instance_port=get_service_port(),
        should_discover=False,
        metadata={"instance_id": get_instance_id()},
    )
    await client.start()
    return client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage database and Eureka lifecycle / 管理数据库与 Eureka 生命周期。"""
    init_db()
    client = None
    try:
        client = await start_eureka_client()
    except Exception:
        logger.exception("Unable to register %s with Eureka", get_instance_id())
    app.state.eureka_client = client

    try:
        yield
    finally:
        if client is not None:
            try:
                await client.stop()
            except Exception:
                logger.exception("Unable to unregister %s", get_instance_id())


app = FastAPI(title="Library Book Service", lifespan=lifespan)


def add_instance_header(response: Response) -> None:
    """Identify the serving instance / 标识处理请求的实例。"""
    response.headers["X-Service-Instance"] = get_instance_id()


@app.post("/api/books", response_model=BookResponse, status_code=status.HTTP_201_CREATED)
def add_book(payload: BookCreate, response: Response) -> BookResponse:
    """Create a book / 新增图书。"""
    try:
        book = create_book(**payload.model_dump())
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="ISBN already exists") from error
    add_instance_header(response)
    return BookResponse.model_validate(book)


@app.get("/api/books", response_model=list[BookResponse])
def list_books(
    response: Response,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[BookResponse]:
    """List or search books / 列出或搜索图书。"""
    books = search_books(q.strip() if q else None, limit, offset)
    add_instance_header(response)
    logger.info("instance=%s action=search query=%r", get_instance_id(), q)
    return [BookResponse.model_validate(book) for book in books]


@app.get("/api/books/{book_id}", response_model=BookResponse)
def read_book(book_id: int, response: Response) -> BookResponse:
    """Read a book by ID / 按 ID 查询图书。"""
    book = get_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    add_instance_header(response)
    logger.info("instance=%s action=read book_id=%s", get_instance_id(), book_id)
    return BookResponse.model_validate(book)


@app.put("/api/books/{book_id}", response_model=BookResponse)
def edit_book(book_id: int, payload: BookUpdate, response: Response) -> BookResponse:
    """Update a book / 修改图书。"""
    try:
        book = update_book(book_id, payload.model_dump(exclude_unset=True))
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="ISBN already exists") from error
    except TotalBelowBorrowedError as error:
        raise HTTPException(status_code=409, detail="Total copies cannot be below borrowed copies") from error
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    add_instance_header(response)
    return BookResponse.model_validate(book)


@app.delete("/api/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_book(book_id: int) -> Response:
    """Delete an unused book / 删除未借出的图书。"""
    try:
        deleted = delete_book(book_id)
    except BookHasActiveLoansError as error:
        raise HTTPException(status_code=409, detail="Book has borrowed copies") from error
    if not deleted:
        raise HTTPException(status_code=404, detail="Book not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/internal/books/{book_id}/borrow", response_model=InventoryResponse)
def reserve_inventory(book_id: int, response: Response) -> InventoryResponse:
    """Reserve one copy / 预留一个图书副本。"""
    try:
        book = borrow_copy(book_id)
    except InventoryUnavailableError as error:
        raise HTTPException(status_code=409, detail="Book inventory is insufficient") from error
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    add_instance_header(response)
    return InventoryResponse(
        book_id=book.id,
        total_copies=book.total_copies,
        available_copies=book.available_copies,
    )


@app.post("/internal/books/{book_id}/return", response_model=InventoryResponse)
def restore_inventory(book_id: int, response: Response) -> InventoryResponse:
    """Restore one copy / 恢复一个图书副本。"""
    try:
        book = return_copy(book_id)
    except InventoryLimitError as error:
        raise HTTPException(status_code=409, detail="All book copies are already available") from error
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    add_instance_header(response)
    return InventoryResponse(
        book_id=book.id,
        total_copies=book.total_copies,
        available_copies=book.available_copies,
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report instance health / 返回实例健康状态。"""
    logger.info("instance=%s action=health", get_instance_id())
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        instance_id=get_instance_id(),
        port=get_service_port(),
    )
