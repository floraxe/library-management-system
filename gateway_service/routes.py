"""HTTP forwarding helpers / HTTP 转发辅助函数。"""

import os
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request, Response, status

from .auth_filter import AuthenticatedUser


HTTP_TIMEOUT_SECONDS = 10.0
IDENTITY_HEADERS = {"x-user-id", "x-user-role"}
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
REQUEST_HEADERS_TO_REMOVE = HOP_BY_HOP_HEADERS | {"host", "content-length"} | IDENTITY_HEADERS
RESPONSE_HEADERS_TO_REMOVE = HOP_BY_HOP_HEADERS | {
    "content-encoding",
    "content-length",
}


def get_upstream_url(environment_name: str) -> str:
    """Read and validate an upstream URL / 读取并校验上游 URL。"""
    upstream_url = os.getenv(environment_name, "").strip()
    parsed_url = urlsplit(upstream_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{environment_name} is not configured",
        )
    return upstream_url


def build_target_url(upstream_url: str, request_path: str) -> str:
    """Join an upstream base URL and path / 拼接上游地址与请求路径。"""
    return f"{upstream_url.rstrip('/')}/{request_path.lstrip('/')}"


def build_request_headers(
    request: Request,
    user: AuthenticatedUser | None,
) -> dict[str, str]:
    """Build trusted proxy headers / 构造可信代理请求头。"""
    headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower() not in REQUEST_HEADERS_TO_REMOVE
    }
    if user is not None:
        headers["X-User-Id"] = user.user_id
        headers["X-User-Role"] = user.role
    return headers


def build_response_headers(response: httpx.Response) -> dict[str, str]:
    """Filter unsafe downstream response headers / 过滤不安全的下游响应头。"""
    return {
        name: value
        for name, value in response.headers.items()
        if name.lower() not in RESPONSE_HEADERS_TO_REMOVE
    }


def create_http_client() -> httpx.AsyncClient:
    """Create a bounded HTTP client / 创建带超时的 HTTP 客户端。"""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(HTTP_TIMEOUT_SECONDS),
        follow_redirects=False,
        trust_env=False,
    )


async def forward_request(
    request: Request,
    upstream_environment: str,
    include_identity: bool,
) -> Response:
    """Forward one request to an upstream / 转发单个请求到上游。"""
    upstream_url = get_upstream_url(upstream_environment)
    target_url = build_target_url(upstream_url, request.url.path)
    user = getattr(request.state, "user", None) if include_identity else None
    if include_identity and not isinstance(user, AuthenticatedUser):
        raise RuntimeError("Authenticated user context is missing")

    try:
        async with create_http_client() as client:
            upstream_response = await client.request(
                method=request.method,
                url=target_url,
                params=list(request.query_params.multi_items()),
                content=await request.body(),
                headers=build_request_headers(request, user),
            )
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream service is unavailable",
        ) from error

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=build_response_headers(upstream_response),
    )
