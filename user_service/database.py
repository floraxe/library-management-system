"""User database helpers, SQLite for tests / MySQL for deployment.

用户数据库辅助函数：单元测试继续使用 SQLite（不改变原有 pytest 行为），
生产/k8s 部署下通过 DATABASE_URL 切换到 MySQL（对接指导书 4.2 节已经部署好的
MySQL 集群）。上层 models.py 完全不需要改动，两种后端都通过同一个
get_connection() / connection.execute(...) 接口暴露。
"""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlsplit

try:
    import pymysql
    from pymysql.cursors import DictCursor
except ImportError:  # pymysql 只有在使用 mysql:// 时才是必需的
    pymysql = None
    DictCursor = None


def get_database_url() -> str:
    """Read the database URL / 读取数据库 URL。"""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required")
    return database_url


def get_sqlite_path(database_url: str) -> str:
    """Extract a SQLite path / 提取 SQLite 路径。"""
    if database_url == "sqlite:///:memory:":
        return ":memory:"
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError("SQLite DATABASE_URL must use the sqlite:/// format")

    database_path = unquote(database_url.removeprefix("sqlite:///"))
    if not database_path:
        raise RuntimeError("DATABASE_URL must include a database path")
    Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    return database_path


class _MySQLConnectionProxy:
    """Adapt a PyMySQL connection to the sqlite3.Connection surface used here.

    让 PyMySQL 连接对外表现得和 sqlite3.Connection 一样：支持
    connection.execute(sql, params) 直接返回可 fetchone()/fetchall() 的游标，
    以及 commit() / rollback() / close()。这样 models.py 里原来针对
    sqlite3.Connection 写的代码不用改一行。
    """

    def __init__(self, connection: "pymysql.connections.Connection") -> None:
        self._connection = connection

    def execute(self, sql: str, params: tuple = ()):
        """Translate '?' placeholders to '%s' and execute / 转换占位符并执行。"""
        cursor = self._connection.cursor()
        cursor.execute(sql.replace("?", "%s"), params)
        return cursor

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


def get_mysql_connection(database_url: str) -> _MySQLConnectionProxy:
    """Open a MySQL connection from a mysql:// URL / 根据 mysql:// URL 建立连接。"""
    if pymysql is None:
        raise RuntimeError(
            "pymysql is required for a mysql:// DATABASE_URL; "
            "add pymysql to user_service/requirements.txt"
        )
    parsed = urlsplit(database_url)
    database_name = parsed.path.lstrip("/")
    if not database_name:
        raise RuntimeError("MySQL DATABASE_URL must include a database name, e.g. mysql://root:root@mysql:3306/library_users")

    connection = pymysql.connect(
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 3306,
        user=unquote(parsed.username) if parsed.username else "root",
        password=unquote(parsed.password) if parsed.password else "",
        database=database_name,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )
    return _MySQLConnectionProxy(connection)


@contextmanager
def get_connection() -> Iterator[object]:
    """Provide a transactional connection, SQLite or MySQL / 提供事务型数据库连接。"""
    database_url = get_database_url()
    scheme = urlsplit(database_url).scheme

    if scheme == "sqlite":
        connection: object = sqlite3.connect(get_sqlite_path(database_url), timeout=10)
        connection.row_factory = sqlite3.Row  # type: ignore[attr-defined]
        connection.execute("PRAGMA foreign_keys = ON")  # type: ignore[attr-defined]
    elif scheme == "mysql":
        connection = get_mysql_connection(database_url)
    else:
        raise RuntimeError(
            f"Unsupported DATABASE_URL scheme '{scheme}'; use sqlite:// (tests) or mysql:// (deployment)"
        )

    try:
        yield connection
        connection.commit()  # type: ignore[attr-defined]
    except Exception:
        connection.rollback()  # type: ignore[attr-defined]
        raise
    finally:
        connection.close()  # type: ignore[attr-defined]


def init_db() -> None:
    """Create the users table when absent / 在表不存在时创建用户表。"""
    database_url = get_database_url()
    scheme = urlsplit(database_url).scheme

    with get_connection() as connection:
        if scheme == "mysql":
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    username VARCHAR(50) NOT NULL UNIQUE,
                    email VARCHAR(254) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(20) NOT NULL DEFAULT 'user',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        else:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
