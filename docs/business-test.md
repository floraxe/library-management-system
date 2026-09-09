# Library Business Services Test Guide / 图书借阅业务实验

## 1. Install / 安装

Run from the repository root with Python 3.11:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Start the course Eureka Server on `http://localhost:8761/eureka/` before service discovery experiments.

## 2. Database structures / 数据库结构

book-service uses its own database:

```sql
CREATE TABLE books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    isbn TEXT NOT NULL UNIQUE,
    description TEXT,
    total_copies INTEGER NOT NULL,
    available_copies INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

borrow-service uses a separate database and stores only remote IDs:

```sql
CREATE TABLE borrows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    book_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    borrowed_at TEXT NOT NULL,
    returned_at TEXT
);
```

There are no cross-service foreign keys. All inventory changes and user checks use HTTP APIs. SQL and connection creation are isolated in each service's `database.py`; adding MySQL later requires a MySQL connection/SQL adapter selected by `DATABASE_URL`, without changing API handlers.

## 3. Environment / 环境变量

| Variable | Service | Example |
|---|---|---|
| `DATABASE_URL` | book/borrow, set separately | `sqlite:///./data/books.db` |
| `EUREKA_SERVER` | all discovered services | `http://localhost:8761/eureka/` |
| `SERVICE_PORT` | book/borrow | `8002` / `8003` |
| `INSTANCE_ID` | book | `book-8002` |
| `DOWNSTREAM_TIMEOUT_SECONDS` | borrow | `2` |
| `CIRCUIT_BREAKER_FAILURE_THRESHOLD` | borrow | `3` |
| `CIRCUIT_BREAKER_RECOVERY_SECONDS` | borrow | `5` |
| `BOOK_SERVICE_URL` | Gateway only | `http://localhost:8002` |
| `BORROW_SERVICE_URL` | Gateway only | `http://localhost:8003` |

Use different `DATABASE_URL` values in each terminal. Do not put secrets, Tokens, or real passwords in committed files.

## 4. Full-stack startup order / 完整服务启动顺序

1. Eureka Server: `8761`
2. user-service: `8012`
3. book-service: `8002`
4. borrow-service: `8003`
5. Gateway: `8011`

Example commands, one terminal per service:

```bash
env DATABASE_URL=sqlite:///./data/users.db \
  JWT_SECRET="$JWT_SECRET" \
  EUREKA_SERVER=http://localhost:8761/eureka/ \
  uvicorn user_service.main:app --host 0.0.0.0 --port 8012
```

```bash
env DATABASE_URL=sqlite:///./data/books.db \
  EUREKA_SERVER=http://localhost:8761/eureka/ \
  SERVICE_PORT=8002 INSTANCE_ID=book-8002 \
  uvicorn book_service.main:app --host 0.0.0.0 --port 8002
```

```bash
env DATABASE_URL=sqlite:///./data/borrows.db \
  EUREKA_SERVER=http://localhost:8761/eureka/ \
  SERVICE_PORT=8003 DOWNSTREAM_TIMEOUT_SECONDS=2 \
  CIRCUIT_BREAKER_FAILURE_THRESHOLD=3 \
  CIRCUIT_BREAKER_RECOVERY_SECONDS=5 \
  uvicorn borrow_service.main:app --host 0.0.0.0 --port 8003
```

```bash
env JWT_SECRET="$JWT_SECRET" \
  EUREKA_SERVER=http://localhost:8761/eureka/ \
  USER_SERVICE_URL=http://localhost:8012 \
  BOOK_SERVICE_URL=http://localhost:8002 \
  BORROW_SERVICE_URL=http://localhost:8003 \
  uvicorn gateway_service.main:app --host 0.0.0.0 --port 8011
```

Allow one Eureka registry refresh interval before the first cross-service borrow request.

## 5. CRUD, borrow, and return curls / 业务 curl

Create a user and capture a JWT through Gateway:

```bash
curl -sS -X POST http://localhost:8011/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"reader1","email":"reader1@example.com","password":"development-password-123"}'

TOKEN=$(curl -fsS -X POST http://localhost:8011/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"reader1","password":"development-password-123"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
```

Create, read, search, and update a book:

```bash
curl -sS -X POST http://localhost:8011/api/books \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Cloud Native Python","author":"Alice Zhang","isbn":"978-LAB-001","total_copies":2}'

curl -sS http://localhost:8011/api/books/1 -H "Authorization: Bearer $TOKEN"
curl -sS 'http://localhost:8011/api/books?q=Cloud' -H "Authorization: Bearer $TOKEN"

curl -sS -X PUT http://localhost:8011/api/books/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Practical Cloud Native Python","total_copies":3}'
```

Borrow, list personal records, and return:

```bash
curl -sS -X POST http://localhost:8011/api/borrows \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"book_id":1}'

curl -sS http://localhost:8011/api/borrows/me \
  -H "Authorization: Bearer $TOKEN"

curl -sS -X POST http://localhost:8011/api/borrows/1/return \
  -H "Authorization: Bearer $TOKEN"
```

Repeating the final return must produce `409 Conflict`.

## 6. Round-robin experiment on 8002 and 8012 / 轮询实验

Port `8012` is normally occupied by user-service. Run this as a separate load-balancing phase: stop user-service temporarily, then start two book-service instances with independent development databases.

```bash
env DATABASE_URL=sqlite:///./data/books-8002.db \
  EUREKA_SERVER=http://localhost:8761/eureka/ \
  SERVICE_PORT=8002 INSTANCE_ID=book-8002 \
  uvicorn book_service.main:app --host 0.0.0.0 --port 8002 --log-level info
```

```bash
env DATABASE_URL=sqlite:///./data/books-8012.db \
  EUREKA_SERVER=http://localhost:8761/eureka/ \
  SERVICE_PORT=8012 INSTANCE_ID=book-8012 \
  uvicorn book_service.main:app --host 0.0.0.0 --port 8012 --log-level info
```

Create the same book in both development databases, then use the real Eureka registry with the borrow-service client as a discovery probe:

```bash
for PORT in 8002 8012; do
  curl -sS -X POST "http://localhost:${PORT}/api/books" \
    -H 'Content-Type: application/json' \
    -d '{"title":"Load Balance Book","author":"Lab","isbn":"978-LB-001","total_copies":5}'
done

python -c '
import asyncio, logging
from py_eureka_client.eureka_client import EurekaClient
from borrow_service.clients import EurekaServiceResolver, LibraryServiceClient
async def main():
    logging.basicConfig(level=logging.INFO)
    registry = EurekaClient(eureka_server="http://localhost:8761/eureka/", should_register=False, should_discover=True)
    await registry.start()
    client = LibraryServiceClient(EurekaServiceResolver(registry))
    try:
        for _ in range(6):
            await client.get_book(1)
    finally:
        await client.close()
        await registry.stop()
asyncio.run(main())'
```

Expected client logs alternate between targets containing `:8002` and `:8012`:

```text
load_balance service=book-service selected=http://...:8002 candidates=2
load_balance service=book-service selected=http://...:8012 candidates=2
```

Book logs and `X-Service-Instance` identify `book-8002` and `book-8012` respectively.

## 7. Circuit-breaker experiment / 熔断实验

Use the full-stack layout with book-service on `8002`. Set the borrow-service threshold to `2` and recovery window to `5` seconds, then stop book-service.

```bash
curl -i -X POST http://localhost:8011/api/borrows \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"book_id":1}'

curl -i -X POST http://localhost:8011/api/borrows \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"book_id":1}'

curl -i -X POST http://localhost:8011/api/borrows \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"book_id":1}'
```

Failures return `503`. Once open, the response contains `CIRCUIT_OPEN`, a clear degraded message, `retry_after_seconds`, and the `Retry-After` header. Check state with:

```bash
curl -sS http://localhost:8003/health
```

Restart book-service with the same database, wait longer than five seconds, and repeat the borrow request. The half-open probe should succeed and `/health` should report the book-service breaker as `closed` again.

## 8. Automated tests / 自动化测试

```bash
pytest -q
```

The tests cover book CRUD/search, inventory exhaustion, successful borrowing, duplicate return, personal records, deterministic round-robin order, open-circuit degradation, and recovery.
