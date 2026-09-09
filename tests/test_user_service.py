"""User service API tests / 用户服务 API 测试。"""

from collections.abc import Iterator

import jwt
import pytest
from fastapi.testclient import TestClient

from user_service.main import app
from user_service.models import get_user_by_username


TEST_JWT_SECRET = "test-jwt-secret-with-at-least-32-bytes"
REGISTER_PAYLOAD = {
    "username": "Alice",
    "email": "Alice@Example.com",
    "password": "correct-horse-battery-staple",
}


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """Create an isolated API client / 创建隔离的 API 客户端。"""
    database_path = tmp_path / "users.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
    monkeypatch.delenv("EUREKA_SERVER", raising=False)

    with TestClient(app) as test_client:
        yield test_client


def register_user(client: TestClient) -> dict[str, object]:
    """Register the shared test user / 注册共用测试用户。"""
    response = client.post("/auth/register", json=REGISTER_PAYLOAD)
    assert response.status_code == 201
    return response.json()


def test_register_hashes_password(client: TestClient) -> None:
    """Store only a password hash / 仅存储密码哈希。"""
    body = register_user(client)

    assert body["username"] == "alice"
    assert body["email"] == "alice@example.com"
    assert "password" not in body
    assert "password_hash" not in body

    stored_user = get_user_by_username("alice")
    assert stored_user is not None
    assert stored_user.password_hash != REGISTER_PAYLOAD["password"]
    assert stored_user.password_hash.startswith("pbkdf2_sha256$")


def test_login_with_correct_password_returns_jwt(client: TestClient) -> None:
    """Return a valid JWT for correct credentials / 正确凭据返回有效 JWT。"""
    user = register_user(client)
    response = client.post(
        "/auth/login",
        json={"username": "ALICE", "password": REGISTER_PAYLOAD["password"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600

    claims = jwt.decode(body["access_token"], TEST_JWT_SECRET, algorithms=["HS256"])
    assert claims["sub"] == str(user["id"])
    assert claims["role"] == "user"
    assert claims["exp"] > claims["iat"]


def test_login_with_wrong_password_returns_401(client: TestClient) -> None:
    """Reject an incorrect password / 拒绝错误密码。"""
    register_user(client)
    response = client.post(
        "/auth/login",
        json={"username": "alice", "password": "definitely-wrong"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_valid_jwt_can_read_user(client: TestClient) -> None:
    """Allow a valid JWT to read a user / 允许有效 JWT 查询用户。"""
    user = register_user(client)
    login_response = client.post(
        "/auth/login",
        json={"username": "alice", "password": REGISTER_PAYLOAD["password"]},
    )
    token = login_response.json()["access_token"]

    response = client.get(
        f"/users/{user['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == user["id"]
    assert "password_hash" not in response.json()
