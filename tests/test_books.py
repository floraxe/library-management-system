"""Book service tests / 图书服务测试。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from book_service.main import app


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """Create an isolated book client / 创建隔离的图书客户端。"""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'books.db'}")
    monkeypatch.setenv("SERVICE_PORT", "8002")
    monkeypatch.setenv("INSTANCE_ID", "book-test-8002")
    monkeypatch.delenv("EUREKA_SERVER", raising=False)
    with TestClient(app) as test_client:
        yield test_client


def create_book(client: TestClient, copies: int = 2) -> dict[str, object]:
    """Create the shared test book / 创建共用测试图书。"""
    response = client.post(
        "/api/books",
        json={
            "title": "Cloud Native Python",
            "author": "Alice Zhang",
            "isbn": "978-TEST-001",
            "description": "Microservice laboratory",
            "total_copies": copies,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_book_crud_and_search(client: TestClient) -> None:
    """Verify create, read, update, search, and delete / 验证图书增查改搜删。"""
    book = create_book(client)
    book_id = book["id"]
    assert book["available_copies"] == 2

    read_response = client.get(f"/api/books/{book_id}")
    assert read_response.status_code == 200
    assert read_response.headers["x-service-instance"] == "book-test-8002"

    update_response = client.put(
        f"/api/books/{book_id}",
        json={"title": "Practical Cloud Native Python", "total_copies": 3},
    )
    assert update_response.status_code == 200
    assert update_response.json()["available_copies"] == 3

    search_response = client.get("/api/books", params={"q": "Practical"})
    assert search_response.status_code == 200
    assert [item["id"] for item in search_response.json()] == [book_id]

    delete_response = client.delete(f"/api/books/{book_id}")
    assert delete_response.status_code == 204
    assert client.get(f"/api/books/{book_id}").status_code == 404


def test_inventory_insufficient_and_return_limit(client: TestClient) -> None:
    """Reject exhausted and over-returned inventory / 拒绝库存不足与超额归还。"""
    book = create_book(client, copies=1)
    book_id = book["id"]

    first_borrow = client.post(f"/internal/books/{book_id}/borrow")
    assert first_borrow.status_code == 200
    assert first_borrow.json()["available_copies"] == 0

    second_borrow = client.post(f"/internal/books/{book_id}/borrow")
    assert second_borrow.status_code == 409
    assert second_borrow.json()["detail"] == "Book inventory is insufficient"

    returned = client.post(f"/internal/books/{book_id}/return")
    assert returned.status_code == 200
    assert returned.json()["available_copies"] == 1

    duplicate_inventory_return = client.post(f"/internal/books/{book_id}/return")
    assert duplicate_inventory_return.status_code == 409
