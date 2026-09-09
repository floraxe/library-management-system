"""Gateway authentication and forwarding tests / Gateway 鉴权与转发测试。"""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from gateway_service import routes
from gateway_service.main import app


TEST_JWT_SECRET = "test-jwt-secret-with-at-least-32-bytes"


@pytest.fixture
def client(monkeypatch) -> Iterator[TestClient]:
    """Create a configured Gateway client / 创建已配置的 Gateway 客户端。"""
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("USER_SERVICE_URL", "http://user-service.test")
    monkeypatch.setenv("BOOK_SERVICE_URL", "http://book-service.test")
    monkeypatch.setenv("BORROW_SERVICE_URL", "http://borrow-service.test")
    monkeypatch.delenv("EUREKA_SERVER", raising=False)

    with TestClient(app) as test_client:
        yield test_client


def create_token(user_id: str = "42", role: str = "user") -> str:
    """Create a valid test token / 创建有效测试令牌。"""
    issued_at = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user_id,
            "role": role,
            "iat": issued_at,
            "exp": issued_at + timedelta(minutes=5),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


def install_mock_upstream(monkeypatch, handler) -> None:
    """Route HTTPX calls to a mock transport / 将 HTTPX 调用指向模拟传输。"""
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        routes,
        "create_http_client",
        lambda: httpx.AsyncClient(transport=transport),
    )


def test_books_without_token_returns_401(client: TestClient) -> None:
    """Reject a missing Token / 拒绝缺失 Token。"""
    response = client.get("/api/books")

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing access token"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_borrows_with_invalid_token_returns_401(client: TestClient) -> None:
    """Reject an invalid Token / 拒绝错误 Token。"""
    response = client.get(
        "/api/borrows",
        headers={"Authorization": "Bearer not-a-valid-jwt"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing access token"}


@pytest.mark.parametrize(
    ("path", "expected_host"),
    [
        ("/api/books?category=cloud&category=python", "book-service.test"),
        ("/api/borrows/current", "borrow-service.test"),
    ],
)
def test_valid_token_is_forwarded_with_trusted_headers(
    client: TestClient,
    monkeypatch,
    path: str,
    expected_host: str,
) -> None:
    """Forward verified identity to protected services / 向受保护服务转发已验证身份。"""
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json={"forwarded": True})

    install_mock_upstream(monkeypatch, handler)
    response = client.get(
        path,
        headers={
            "Authorization": f"Bearer {create_token()}",
            "X-User-Id": "forged-id",
            "X-User-Role": "admin",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"forwarded": True}
    assert len(captured_requests) == 1
    forwarded_request = captured_requests[0]
    assert forwarded_request.url.host == expected_host
    assert forwarded_request.headers["x-user-id"] == "42"
    assert forwarded_request.headers["x-user-role"] == "user"


def test_login_is_public_and_forwarded(client: TestClient, monkeypatch) -> None:
    """Forward login without requiring a Token / 登录无需 Token 即可转发。"""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://user-service.test/auth/login")
        return httpx.Response(200, json={"access_token": "test", "token_type": "bearer"})

    install_mock_upstream(monkeypatch, handler)
    response = client.post(
        "/auth/login",
        json={"username": "alice", "password": "correct-horse-battery-staple"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "test"
