"""User persistence model / 用户持久化模型。"""

import sqlite3
from dataclasses import dataclass

from .database import get_connection


USER_COLUMNS = "id, username, email, password_hash, role, created_at"


@dataclass(frozen=True)
class User:
    """Represent one stored user / 表示一个已存储用户。"""

    id: int
    username: str
    email: str
    password_hash: str
    role: str
    created_at: str


def row_to_user(row: sqlite3.Row) -> User:
    """Map a database row to User / 将数据库行映射为用户对象。"""
    return User(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        password_hash=row["password_hash"],
        role=row["role"],
        created_at=row["created_at"],
    )


def create_user(username: str, email: str, password_hash: str) -> User:
    """Insert and return a user / 新增并返回用户。"""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO users (username, email, password_hash, role)
            VALUES (?, ?, ?, 'user')
            """,
            (username, email, password_hash),
        )
        row = connection.execute(
            f"SELECT {USER_COLUMNS} FROM users WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()

    if row is None:
        raise RuntimeError("Created user could not be loaded")
    return row_to_user(row)


def get_user_by_id(user_id: int) -> User | None:
    """Find a user by ID / 按 ID 查询用户。"""
    with get_connection() as connection:
        row = connection.execute(
            f"SELECT {USER_COLUMNS} FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return row_to_user(row) if row else None


def get_user_by_username(username: str) -> User | None:
    """Find a user by username / 按用户名查询用户。"""
    with get_connection() as connection:
        row = connection.execute(
            f"SELECT {USER_COLUMNS} FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    return row_to_user(row) if row else None


def get_user_by_email(email: str) -> User | None:
    """Find a user by email / 按邮箱查询用户。"""
    with get_connection() as connection:
        row = connection.execute(
            f"SELECT {USER_COLUMNS} FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    return row_to_user(row) if row else None
