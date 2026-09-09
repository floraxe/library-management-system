"""Borrow service, balancing, and circuit tests / 借阅、负载均衡与熔断测试。"""

import asyncio
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from borrow_service.circuit_breaker import CircuitBreaker
from borrow_service.clients import (
    BOOK_SERVICE,
    USER_SERVICE,
    LibraryServiceClient,
    ServiceCallError,
)
from borrow_service.main import app, get_service_client


class FakeLibraryClient:
    """Provide deterministic downstream behavior / 提供确定性的下游行为。"""

    def __init__(self) -> None:
        self.borrow_calls: list[tuple[int, str]] = []
        self.return_calls: list[int] = []

    async def validate_user(self, user_id: str, authorization: str | None) -> dict[str, object]:
        return {"id": int(user_id), "role": "user"}

    async def get_book(self, book_id: int) -> tuple[dict[str, object], str]:
        return {"id": book_id, "available_copies": 1}, "http://book-instance.test"

    async def borrow_book(self, book_id: int, selected_url: str) -> dict[str, object]:
        self.borrow_calls.append((book_id, selected_url))
        return {"book_id": book_id, "available_copies": 0}

    async def return_book(
        self,
        book_id: int,
        selected_url: str | None = None,
    ) -> dict[str, object]:
        self.return_calls.append(book_id)
        return {"book_id": book_id, "available_copies": 1}

    def breaker_state(self, service_name: str) -> str:
        return "closed"


class StaticResolver:
    """Return fixed test instances / 返回固定测试实例。"""

    def __init__(self, services: dict[str, list[str]]) -> None:
        self.services = services

    def get_urls(self, service_name: str) -> list[str]:
        return self.services[service_name]


@pytest.fixture
def borrow_client(tmp_path, monkeypatch) -> Iterator[tuple[TestClient, FakeLibraryClient]]:
    """Create an isolated borrow API / 创建隔离的借阅 API。"""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'borrows.db'}")
    monkeypatch.setenv("SERVICE_PORT", "8003")
    monkeypatch.delenv("EUREKA_SERVER", raising=False)
    fake_client = FakeLibraryClient()
    app.dependency_overrides[get_service_client] = lambda: fake_client
    try:
        with TestClient(app) as test_client:
            yield test_client, fake_client
    finally:
        app.dependency_overrides.clear()


def test_successful_borrow_and_personal_records(
    borrow_client: tuple[TestClient, FakeLibraryClient],
) -> None:
    """Create and list the current user's borrow / 创建并查询当前用户借阅。"""
    client, fake_client = borrow_client
    created = client.post(
        "/borrows",
        json={"book_id": 7},
        headers={"X-User-Id": "42", "Authorization": "Bearer test-only"},
    )

    assert created.status_code == 201
    assert created.json()["status"] == "borrowed"
    assert created.json()["user_id"] == "42"
    assert fake_client.borrow_calls == [(7, "http://book-instance.test")]

    mine = client.get("/borrows/me", headers={"X-User-Id": "42"})
    assert mine.status_code == 200
    assert [record["id"] for record in mine.json()] == [created.json()["id"]]

    another_user = client.get("/borrows/me", headers={"X-User-Id": "99"})
    assert another_user.json() == []


def test_duplicate_return_is_rejected(
    borrow_client: tuple[TestClient, FakeLibraryClient],
) -> None:
    """Return inventory only once / 库存只归还一次。"""
    client, fake_client = borrow_client
    created = client.post(
        "/borrows",
        json={"book_id": 9},
        headers={"X-User-Id": "42"},
    ).json()

    returned = client.post(
        f"/borrows/{created['id']}/return",
        headers={"X-User-Id": "42"},
    )
    assert returned.status_code == 200
    assert returned.json()["status"] == "returned"

    duplicate = client.post(
        f"/borrows/{created['id']}/return",
        headers={"X-User-Id": "42"},
    )
    assert duplicate.status_code == 409
    assert fake_client.return_calls == [9]


def test_open_circuit_returns_clear_503(
    borrow_client: tuple[TestClient, FakeLibraryClient],
) -> None:
    """Expose a clear degraded API response / 返回清晰的 API 降级响应。"""
    client, _ = borrow_client

    class OpenCircuitClient(FakeLibraryClient):
        async def validate_user(
            self,
            user_id: str,
            authorization: str | None,
        ) -> dict[str, object]:
            raise ServiceCallError(
                503,
                "CIRCUIT_OPEN",
                "user-service circuit is open; request degraded",
                USER_SERVICE,
                retry_after_seconds=5,
            )

    app.dependency_overrides[get_service_client] = OpenCircuitClient
    response = client.post(
        "/borrows",
        json={"book_id": 7},
        headers={"X-User-Id": "42"},
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert response.json()["detail"]["code"] == "CIRCUIT_OPEN"
    assert "request degraded" in response.json()["detail"]["message"]


def test_round_robin_selects_book_instances() -> None:
    """Alternate consecutive book requests / 连续图书请求轮流选择实例。"""
    selected_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        selected_hosts.append(request.url.host)
        return httpx.Response(200, json={"id": 1, "available_copies": 1})

    async def scenario() -> None:
        transport = httpx.MockTransport(handler)
        http_client = httpx.AsyncClient(transport=transport)
        service_client = LibraryServiceClient(
            StaticResolver(
                {
                    BOOK_SERVICE: ["http://book-a.test:8002", "http://book-b.test:8012"],
                    USER_SERVICE: ["http://user.test:8012"],
                }
            ),
            http_client=http_client,
        )
        try:
            await service_client.get_book(1)
            await service_client.get_book(1)
            await service_client.get_book(1)
            await service_client.get_book(1)
        finally:
            await service_client.close()

    asyncio.run(scenario())
    assert selected_hosts == ["book-a.test", "book-b.test", "book-a.test", "book-b.test"]


def test_circuit_opens_and_recovers() -> None:
    """Degrade while open and recover after timeout / 熔断时降级并在窗口后恢复。"""
    now = [100.0]
    downstream_available = [False]
    transport_calls = [0]

    def clock() -> float:
        return now[0]

    def handler(request: httpx.Request) -> httpx.Response:
        transport_calls[0] += 1
        if not downstream_available[0]:
            raise httpx.ConnectError("book service stopped", request=request)
        return httpx.Response(200, json={"id": 1, "available_copies": 1})

    async def scenario() -> None:
        book_breaker = CircuitBreaker(1, 5.0, clock=clock)
        user_breaker = CircuitBreaker(1, 5.0, clock=clock)
        service_client = LibraryServiceClient(
            StaticResolver(
                {
                    BOOK_SERVICE: ["http://book.test:8002"],
                    USER_SERVICE: ["http://user.test:8012"],
                }
            ),
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            breakers={BOOK_SERVICE: book_breaker, USER_SERVICE: user_breaker},
        )
        try:
            with pytest.raises(ServiceCallError) as first_failure:
                await service_client.get_book(1)
            assert first_failure.value.code == "DOWNSTREAM_UNAVAILABLE"

            with pytest.raises(ServiceCallError) as open_failure:
                await service_client.get_book(1)
            assert open_failure.value.status_code == 503
            assert open_failure.value.code == "CIRCUIT_OPEN"
            assert transport_calls[0] == 1

            now[0] += 6.0
            downstream_available[0] = True
            book, _ = await service_client.get_book(1)
            assert book["id"] == 1
            assert service_client.breaker_state(BOOK_SERVICE) == "closed"
        finally:
            await service_client.close()

    asyncio.run(scenario())
