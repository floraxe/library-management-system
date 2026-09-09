"""Book persistence operations / 图书持久化操作。"""

import sqlite3
from dataclasses import dataclass

from .database import get_connection


BOOK_COLUMNS = (
    "id, title, author, isbn, description, total_copies, "
    "available_copies, created_at, updated_at"
)


class InventoryUnavailableError(Exception):
    """Indicate that no copy is available / 表示没有可借库存。"""


class InventoryLimitError(Exception):
    """Indicate that all copies are already returned / 表示库存已达到上限。"""


class BookHasActiveLoansError(Exception):
    """Prevent deletion while copies are borrowed / 防止删除仍有借出的图书。"""


class TotalBelowBorrowedError(Exception):
    """Prevent reducing total below borrowed copies / 防止总库存低于已借数量。"""


@dataclass(frozen=True)
class Book:
    """Represent a stored book / 表示已存储图书。"""

    id: int
    title: str
    author: str
    isbn: str
    description: str | None
    total_copies: int
    available_copies: int
    created_at: str
    updated_at: str


def row_to_book(row: sqlite3.Row) -> Book:
    """Map one SQLite row / 映射单个 SQLite 数据行。"""
    return Book(**{column: row[column] for column in row.keys()})


def create_book(
    title: str,
    author: str,
    isbn: str,
    description: str | None,
    total_copies: int,
) -> Book:
    """Insert and return a book / 新增并返回图书。"""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO books (title, author, isbn, description, total_copies, available_copies)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, author, isbn, description, total_copies, total_copies),
        )
        row = connection.execute(
            f"SELECT {BOOK_COLUMNS} FROM books WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    if row is None:
        raise RuntimeError("Created book could not be loaded")
    return row_to_book(row)


def get_book(book_id: int) -> Book | None:
    """Find a book by ID / 按 ID 查询图书。"""
    with get_connection() as connection:
        row = connection.execute(
            f"SELECT {BOOK_COLUMNS} FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()
    return row_to_book(row) if row else None


def search_books(keyword: str | None, limit: int, offset: int) -> list[Book]:
    """List books or search common fields / 列出图书或搜索常用字段。"""
    with get_connection() as connection:
        if keyword:
            pattern = f"%{keyword}%"
            rows = connection.execute(
                f"""
                SELECT {BOOK_COLUMNS} FROM books
                WHERE title LIKE ? OR author LIKE ? OR isbn LIKE ?
                ORDER BY id LIMIT ? OFFSET ?
                """,
                (pattern, pattern, pattern, limit, offset),
            ).fetchall()
        else:
            rows = connection.execute(
                f"SELECT {BOOK_COLUMNS} FROM books ORDER BY id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
    return [row_to_book(row) for row in rows]


def update_book(book_id: int, changes: dict[str, object]) -> Book | None:
    """Update allowed book fields / 更新允许修改的图书字段。"""
    allowed_fields = {"title", "author", "isbn", "description", "total_copies"}
    updates = {name: value for name, value in changes.items() if name in allowed_fields}

    with get_connection() as connection:
        current_row = connection.execute(
            f"SELECT {BOOK_COLUMNS} FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()
        if current_row is None:
            return None
        if not updates:
            return row_to_book(current_row)

        if "total_copies" in updates:
            borrowed_copies = current_row["total_copies"] - current_row["available_copies"]
            new_total = int(updates["total_copies"])
            if new_total < borrowed_copies:
                raise TotalBelowBorrowedError
            updates["available_copies"] = new_total - borrowed_copies

        assignments = ", ".join(f"{name} = ?" for name in updates)
        values = [*updates.values(), book_id]
        connection.execute(
            f"UPDATE books SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
        updated_row = connection.execute(
            f"SELECT {BOOK_COLUMNS} FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()
    return row_to_book(updated_row)


def delete_book(book_id: int) -> bool:
    """Delete a book without active loans / 删除没有在借副本的图书。"""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT total_copies, available_copies FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()
        if row is None:
            return False
        if row["available_copies"] != row["total_copies"]:
            raise BookHasActiveLoansError
        connection.execute("DELETE FROM books WHERE id = ?", (book_id,))
    return True


def borrow_copy(book_id: int) -> Book | None:
    """Atomically reserve one available copy / 原子扣减一个可用副本。"""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE books
            SET available_copies = available_copies - 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND available_copies > 0
            """,
            (book_id,),
        )
        if cursor.rowcount == 0:
            exists = connection.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone()
            if exists is None:
                return None
            raise InventoryUnavailableError
        row = connection.execute(
            f"SELECT {BOOK_COLUMNS} FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()
    return row_to_book(row)


def return_copy(book_id: int) -> Book | None:
    """Atomically restore one borrowed copy / 原子恢复一个借出副本。"""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE books
            SET available_copies = available_copies + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND available_copies < total_copies
            """,
            (book_id,),
        )
        if cursor.rowcount == 0:
            exists = connection.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone()
            if exists is None:
                return None
            raise InventoryLimitError
        row = connection.execute(
            f"SELECT {BOOK_COLUMNS} FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()
    return row_to_book(row)
