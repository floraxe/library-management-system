# Library Platform API Contract / 图书馆平台 API 合约

All client traffic enters through `gateway-service` on port `8011`. The examples below use JSON unless stated otherwise.

所有客户端请求统一进入 `8011` 端口的 `gateway-service`。除特别说明外，请求和响应均使用 JSON。

## Authentication / 鉴权

The following paths are public:

- `POST /auth/register`
- `POST /auth/login`
- `GET /health`

Every other Gateway path requires:

```http
Authorization: Bearer <token>
```

A missing, malformed, expired, or incorrectly signed Token returns:

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer
Content-Type: application/json

{"detail":"Invalid or missing access token"}
```

## Register a user / 注册用户

`POST /auth/register`

Request:

```json
{
  "username": "alice",
  "email": "alice@example.com",
  "password": "correct-horse-battery-staple"
}
```

Validation:

- `username`: 3–50 characters; lowercase letters, digits, `.`, `_`, and `-` after normalization.
- `email`: 3–254 characters and a basic `name@domain.tld` shape.
- `password`: 8–128 characters.
- New accounts always receive the `user` role.

Success: `201 Created`

```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@example.com",
  "role": "user",
  "created_at": "2026-09-08T12:00:00"
}
```

Conflict: `409 Conflict` when the username or email already exists.

## Login / 登录

`POST /auth/login`

Request:

```json
{
  "username": "alice",
  "password": "correct-horse-battery-staple"
}
```

Success: `200 OK`

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 3600
}
```

Invalid credentials return `401 Unauthorized` with the common message `Invalid username or password`.

The JWT contains these claims:

| Claim | Meaning |
|---|---|
| `sub` | Numeric user ID encoded as a string |
| `role` | User role |
| `iat` | UTC issue time |
| `exp` | UTC expiration time |

## Read a user / 查询用户

`GET /users/{id}`

Requires a valid Bearer Token. Success returns the same safe user fields as registration. The password hash is never returned. An unknown ID returns `404 Not Found`.

## Health checks / 健康检查

Gateway `GET /health`:

```json
{"status":"ok","service":"gateway-service"}
```

User service `GET http://localhost:8012/health`:

```json
{"status":"ok","service":"user-service"}
```

## Book proxy / 图书代理

The Gateway forwards `/api/books` and `/api/books/**` to the base URL in `BOOK_SERVICE_URL`. The original HTTP method, path, query parameters, body, and applicable headers are preserved.

## Borrow proxy / 借阅代理

The Gateway forwards `/api/borrows` and `/api/borrows/**` to the base URL in `BORROW_SERVICE_URL` with the same forwarding behavior.

For both protected proxies, the Gateway discards client-supplied identity headers and adds trusted values decoded from the JWT:

```http
X-User-Id: <sub>
X-User-Role: <role>
```

If an upstream URL is absent or invalid, the Gateway returns `503 Service Unavailable`. If a configured upstream cannot be reached before the timeout, it returns `502 Bad Gateway`.

## Book service API / 图书服务 API

The public book API is exposed through the Gateway under `/api/books`. Internal inventory endpoints are called only by borrow-service.

### Create a book / 新增图书

`POST /api/books`

```json
{
  "title": "Cloud Native Python",
  "author": "Alice Zhang",
  "isbn": "978-TEST-001",
  "description": "Microservice laboratory",
  "total_copies": 2
}
```

Returns `201 Created` and the stored book. `available_copies` initially equals `total_copies`. A duplicate ISBN returns `409 Conflict`.

### List and search books / 列表与搜索

`GET /api/books?q=<keyword>&limit=100&offset=0`

The optional keyword matches title, author, or ISBN. Every successful book response contains `X-Service-Instance`, which identifies the instance that served the request.

### Read, update, and delete / 查询、修改与删除

- `GET /api/books/{id}`
- `PUT /api/books/{id}` with any subset of `title`, `author`, `isbn`, `description`, and `total_copies`
- `DELETE /api/books/{id}` returning `204 No Content`

`total_copies` cannot be reduced below the currently borrowed count. A book with borrowed copies cannot be deleted.

### Internal inventory / 内部库存

- `POST /internal/books/{id}/borrow`
- `POST /internal/books/{id}/return`

Success response:

```json
{
  "book_id": 1,
  "total_copies": 2,
  "available_copies": 1
}
```

Insufficient inventory or returning beyond total inventory returns `409 Conflict`. Both mutations use conditional SQL updates so concurrent requests cannot make inventory negative or exceed total copies.

## Borrow service API / 借阅服务 API

borrow-service reads the current identity only from the Gateway-injected header:

```http
X-User-Id: <verified-user-id>
```

The original `Authorization` header is forwarded to user-service for independent user validation. Direct service paths use `/borrows`; equivalent `/api/borrows` aliases support the existing Gateway route without changing gateway-service.

### Borrow a book / 借书

`POST /borrows` or Gateway `POST /api/borrows`

```json
{"book_id": 1}
```

Before creating a local record, borrow-service discovers and calls user-service and book-service through Eureka, validates both remote entities, and atomically reserves inventory over HTTP. Success returns `201 Created`:

```json
{
  "id": 1,
  "user_id": "1",
  "book_id": 1,
  "status": "borrowed",
  "borrowed_at": "2026-09-08T12:00:00",
  "returned_at": null
}
```

### My records / 我的借阅

`GET /borrows/me` or Gateway `GET /api/borrows/me`

Returns only records whose `user_id` matches `X-User-Id`, ordered newest first.

### Return a book / 还书

`POST /borrows/{id}/return` or Gateway `POST /api/borrows/{id}/return`

The record is atomically moved through `borrowed → returning → returned`. A downstream failure restores it to `borrowed`; an already returned or in-progress record returns `409 Conflict`.

### Degraded response / 降级响应

Discovery failure, timeout, connection failure, downstream 5xx, or an open circuit returns `503 Service Unavailable`:

```json
{
  "detail": {
    "code": "CIRCUIT_OPEN",
    "message": "book-service circuit is open; request degraded",
    "service": "book-service",
    "retry_after_seconds": 5
  }
}
```

Open-circuit responses include `Retry-After`. After the recovery window, one half-open probe is allowed; success closes the circuit.
