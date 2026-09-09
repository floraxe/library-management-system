# Python Library Microservices Platform

云原生技术实践第二章的微服务实现，包含用户、图书、借阅服务和统一 API 网关。运行环境为 Python 3.11。

## Architecture / 架构

```text
                         Eureka :8761
                         /          \
              gateway-service     user-service
                   :8011              :8012
                     |
       +-------------+------------------+
       |             |                  |
   /auth, /users  /api/books/**   /api/borrows/**
       |             |                  |
  user-service   book-service      borrow-service
                     :8002              :8003
                                           |
                                  Eureka + HTTPX calls
```

- `gateway-service` exposes the public entry point and verifies JWTs.
- `user-service` stores users in SQLite, hashes passwords, and issues JWTs.
- `book-service` owns book metadata and inventory.
- `borrow-service` owns borrow records and calls user/book services through Eureka discovery and HTTPX.
- Gateway proxy targets come from environment variables; borrow-service never reads another service's database.
- When `EUREKA_SERVER` is present, services register themselves and unregister during graceful shutdown.

## Files / 文件结构

```text
.
├── .env.example
├── .gitignore
├── README.md
├── docs/api-contract.md
├── docs/business-test.md
├── book_service/
│   ├── database.py
│   ├── main.py
│   ├── models.py
│   ├── requirements.txt
│   └── schemas.py
├── borrow_service/
│   ├── circuit_breaker.py
│   ├── clients.py
│   ├── database.py
│   ├── main.py
│   ├── models.py
│   ├── requirements.txt
│   └── schemas.py
├── gateway_service/
│   ├── auth_filter.py
│   ├── main.py
│   ├── requirements.txt
│   └── routes.py
├── requirements-dev.txt
├── tests/
│   ├── test_gateway_service.py
│   └── test_user_service.py
└── user_service/
    ├── auth.py
    ├── database.py
    ├── main.py
    ├── models.py
    ├── requirements.txt
    └── schemas.py
```

## Install / 安装

Run from the repository root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Generate a development secret and copy the printed value into `JWT_SECRET` in the local `.env` file:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Never commit `.env`, generated Tokens, passwords, or SQLite files.

## Environment / 环境变量

| Variable | Required | Description |
|---|---:|---|
| `JWT_SECRET` | Yes | Shared HS256 key used by user-service and Gateway; at least 32 bytes |
| `JWT_EXPIRE_MINUTES` | No | Token lifetime in minutes; defaults to `60` |
| `DATABASE_URL` | user-service | SQLite URL such as `sqlite:///./data/users.db` |
| `EUREKA_SERVER` | For registration | Eureka URL such as `http://localhost:8761/eureka/`; registration is skipped when absent |
| `USER_SERVICE_URL` | Gateway | User-service base URL, normally `http://localhost:8012` |
| `BOOK_SERVICE_URL` | Book routes | Existing book-service base URL |
| `BORROW_SERVICE_URL` | Borrow routes | Existing borrow-service base URL |

Load the local file into each service terminal:

```bash
set -a
source .env
set +a
```

## Start services / 启动服务

First start the course-provided Eureka Server on port `8761`. Confirm it is reachable:

```bash
curl -fsS http://localhost:8761/
```

Start user-service in one terminal:

```bash
source .venv/bin/activate
set -a
source .env
set +a
uvicorn user_service.main:app --host 0.0.0.0 --port 8012
```

Start Gateway in another terminal:

```bash
source .venv/bin/activate
set -a
source .env
set +a
uvicorn gateway_service.main:app --host 0.0.0.0 --port 8011
```

Check health and Eureka registration:

```bash
curl -fsS http://localhost:8012/health
curl -fsS http://localhost:8011/health
curl -fsS -H 'Accept: application/json' http://localhost:8761/eureka/apps/USER-SERVICE
curl -fsS -H 'Accept: application/json' http://localhost:8761/eureka/apps/GATEWAY-SERVICE
```

## Test / 测试

```bash
source .venv/bin/activate
pytest -q
```

The tests use isolated temporary SQLite databases and mocked HTTPX upstreams. They do not require Eureka, book-service, or borrow-service.

## Copyable API checks / 可复制 API 验证

Register through Gateway:

```bash
curl -i -X POST http://localhost:8011/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","email":"alice@example.com","password":"correct-horse-battery-staple"}'
```

Log in through Gateway and capture the returned JWT in the current shell:

```bash
TOKEN=$(curl -fsS -X POST http://localhost:8011/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"correct-horse-battery-staple"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
```

Verify authentication failures:

```bash
curl -i http://localhost:8011/api/books
curl -i http://localhost:8011/api/borrows
curl -i http://localhost:8011/api/books \
  -H 'Authorization: Bearer invalid-token'
```

Verify authenticated forwarding after the corresponding downstream services and URLs are configured:

```bash
curl -i http://localhost:8011/api/books \
  -H "Authorization: Bearer $TOKEN"
curl -i http://localhost:8011/api/borrows \
  -H "Authorization: Bearer $TOKEN"
```

Query the registered user through Gateway:

```bash
curl -i http://localhost:8011/users/1 \
  -H "Authorization: Bearer $TOKEN"
```

See [docs/api-contract.md](docs/api-contract.md) for the complete API contract and [docs/business-test.md](docs/business-test.md) for book, borrow, round-robin, and circuit-breaker experiments.
