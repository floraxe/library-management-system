"""Gateway rate limiting filter / Gateway 限流过滤器。"""

import time
from collections import defaultdict, deque

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint


RATE_LIMIT_MAX_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 10.0

# In-memory sliding window keyed by client address.
# 基于内存的滑动窗口计数，按客户端地址分组。
_request_log: dict[str, deque[float]] = defaultdict(deque)


def _client_key(request: Request) -> str:
    """Identify the caller for rate limiting / 识别限流所依据的调用方。"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _too_many_requests_response(retry_after_seconds: float) -> JSONResponse:
    """Build a consistent 429 response / 构造统一的 429 响应。"""
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "Too many requests, please slow down"},
        headers={"Retry-After": str(max(1, int(retry_after_seconds) + 1))},
    )


async def rate_limit_filter(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    """Reject bursts beyond the configured window / 拒绝超过窗口配置的突发请求。"""
    key = _client_key(request)
    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    log = _request_log[key]

    while log and log[0] < window_start:
        log.popleft()

    if len(log) >= RATE_LIMIT_MAX_REQUESTS:
        retry_after = log[0] + RATE_LIMIT_WINDOW_SECONDS - now
        return _too_many_requests_response(retry_after)

    log.append(now)
    return await call_next(request)