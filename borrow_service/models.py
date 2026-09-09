"""Borrow persistence operations / 借阅持久化操作。"""

import sqlite3
from dataclasses import dataclass

from .database import get_connection


BORROWED = "borrowed"
RETURNING = "returning"
RETURNED = "returned"
BORROW_COLUMNS = "id, user_id, book_id, status, borrowed_at, returned_at"


@dataclass(frozen=True)
class BorrowRecord:
    """Represent one borrow record / 表示一条借阅记录。"""

    id: int
    user_id: str
    book_id: int
    status: str
    borrowed_at: str
    returned_at: str | None


def row_to_borrow(row: sqlite3.Row) -> BorrowRecord:
    """Map one SQLite row / 映射单个 SQLite 数据行。"""
    return BorrowRecord(**{column: row[column] for column in row.keys()})


def create_borrow(user_id: str, book_id: int) -> BorrowRecord:
    """Create a borrowed record / 创建在借记录。"""
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO borrows (user_id, book_id, status) VALUES (?, ?, ?)",
            (user_id, book_id, BORROWED),
        )
        row = connection.execute(
            f"SELECT {BORROW_COLUMNS} FROM borrows WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    if row is None:
        raise RuntimeError("Created borrow record could not be loaded")
    return row_to_borrow(row)


def get_borrow(borrow_id: int, user_id: str) -> BorrowRecord | None:
    """Find a user's borrow record / 查询用户的一条借阅记录。"""
    with get_connection() as connection:
        row = connection.execute(
            f"SELECT {BORROW_COLUMNS} FROM borrows WHERE id = ? AND user_id = ?",
            (borrow_id, user_id),
        ).fetchone()
    return row_to_borrow(row) if row else None


def list_user_borrows(user_id: str) -> list[BorrowRecord]:
    """List a user's borrow records / 列出用户的借阅记录。"""
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT {BORROW_COLUMNS} FROM borrows
            WHERE user_id = ? ORDER BY id DESC
            """,
            (user_id,),
        ).fetchall()
    return [row_to_borrow(row) for row in rows]


def claim_return(borrow_id: int, user_id: str) -> tuple[BorrowRecord | None, bool]:
    """Atomically claim a record for return / 原子认领待归还记录。"""
    with get_connection() as connection:
        row = connection.execute(
            f"SELECT {BORROW_COLUMNS} FROM borrows WHERE id = ? AND user_id = ?",
            (borrow_id, user_id),
        ).fetchone()
        if row is None:
            return None, False
        if row["status"] != BORROWED:
            return row_to_borrow(row), False

        cursor = connection.execute(
            """
            UPDATE borrows SET status = ?
            WHERE id = ? AND user_id = ? AND status = ?
            """,
            (RETURNING, borrow_id, user_id, BORROWED),
        )
        updated = connection.execute(
            f"SELECT {BORROW_COLUMNS} FROM borrows WHERE id = ? AND user_id = ?",
            (borrow_id, user_id),
        ).fetchone()
    return row_to_borrow(updated), cursor.rowcount == 1


def cancel_return(borrow_id: int, user_id: str) -> None:
    """Restore a failed return attempt / 恢复失败的归还操作。"""
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE borrows SET status = ?
            WHERE id = ? AND user_id = ? AND status = ?
            """,
            (BORROWED, borrow_id, user_id, RETURNING),
        )


def complete_return(borrow_id: int, user_id: str) -> BorrowRecord:
    """Complete a claimed return / 完成已认领的归还操作。"""
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE borrows
            SET status = ?, returned_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ? AND status = ?
            """,
            (RETURNED, borrow_id, user_id, RETURNING),
        )
        row = connection.execute(
            f"SELECT {BORROW_COLUMNS} FROM borrows WHERE id = ? AND user_id = ?",
            (borrow_id, user_id),
        ).fetchone()
    if row is None or row["status"] != RETURNED:
        raise RuntimeError("Borrow return could not be completed")
    return row_to_borrow(row)
