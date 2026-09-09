"""Eureka-discovered downstream clients / 基于 Eureka 发现的下游客户端。"""

import logging
import math
from threading import Lock
from typing import Protocol

import httpx
from py_eureka_client.eureka_basic import Instance
from py_eureka_client.eureka_client import EurekaClient

from .circuit_breaker import CircuitBreaker, CircuitOpenError


USER_SERVICE = "user-service"
BOOK_SERVICE = "book-service"
logger = logging.getLogger(__name__)


class ServiceCallError(Exception):
    """Represent a clear downstream failure / 表示清晰的下游调用失败。"""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        service: str,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.service = service
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)

    def detail(self) -> dict[str, object]:
        """Build a stable API error body / 构造稳定的 API 错误内容。"""
        detail: dict[str, object] = {
            "code": self.code,
            "message": self.message,
            "service": self.service,
        }
        if self.retry_after_seconds is not None:
            detail["retry_after_seconds"] = self.retry_after_seconds
        return detail


class ServiceResolver(Protocol):
    """Define the discovery boundary / 定义服务发现边界。"""

    def get_urls(self, service_name: str) -> list[str]:
        """Return current UP instance URLs / 返回当前 UP 实例地址。"""


class EurekaServiceResolver:
    """Resolve UP instances from py-eureka-client / 从 Eureka 客户端解析 UP 实例。"""

    def __init__(self, client: EurekaClient | None) -> None:
        self.client = client

    @staticmethod
    def instance_url(instance: Instance) -> str | None:
        """Convert an Eureka instance to a base URL / 将 Eureka 实例转换为基础 URL。"""
        # 优先用 ipAddr（k8s Pod IP，集群内总是可路由），不要优先用
        # homePageUrl —— py-eureka-client 会用容器自己的 hostname（也就是
        # k8s 的 Pod 名字，例如 user-service-6d68c4bdc6-x5bt9）拼出
        # homePageUrl，而这个名字在 k8s 集群 DNS 里根本无法解析，一连接
        # 就会立刻失败。只有当 ipAddr/hostName 都拿不到时才退回用它。
        host = instance.ipAddr or instance.hostName
        if host:
            if instance.securePort and instance.securePort.enabled:
                return f"https://{host}:{instance.securePort.port}"
            if instance.port and instance.port.enabled:
                return f"http://{host}:{instance.port.port}"

        if instance.homePageUrl:
            return instance.homePageUrl.rstrip("/")
        return None

    def get_urls(self, service_name: str) -> list[str]:
        """Read current service URLs from Eureka / 从 Eureka 读取当前服务地址。"""
        if self.client is None:
            raise ServiceCallError(
                503,
                "SERVICE_REGISTRY_UNAVAILABLE",
                "Eureka service registry is not configured",
                service_name,
            )
        try:
            application = self.client.applications.get_application(service_name)
            urls = [self.instance_url(instance) for instance in application.up_instances]
        except Exception as error:
            raise ServiceCallError(
                503,
                "SERVICE_DISCOVERY_FAILED",
                f"Unable to discover {service_name}",
                service_name,
            ) from error

        available_urls = sorted({url for url in urls if url})
        if not available_urls:
            raise ServiceCallError(
                503,
                "NO_SERVICE_INSTANCE",
                f"No UP instance is available for {service_name}",
                service_name,
            )
        return available_urls


class RoundRobinBalancer:
    """Select discovered instances in round-robin order / 轮询选择已发现实例。"""

    def __init__(self, resolver: ServiceResolver) -> None:
        self.resolver = resolver
        self._positions: dict[str, int] = {}
        self._lock = Lock()

    def select(self, service_name: str) -> str:
        """Select the next current instance / 选择下一个当前实例。"""
        urls = self.resolver.get_urls(service_name)
        with self._lock:
            position = self._positions.get(service_name, 0)
            selected = urls[position % len(urls)]
            self._positions[service_name] = position + 1
        logger.info(
            "load_balance service=%s selected=%s candidates=%s",
            service_name,
            selected,
            len(urls),
        )
        return selected


def response_detail(response: httpx.Response, fallback: str) -> str:
    """Extract a safe downstream error message / 提取安全的下游错误信息。"""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return fallback
    return detail if isinstance(detail, str) and detail else fallback


class LibraryServiceClient:
    """Call user and book services with balancing and breakers / 使用负载均衡与熔断调用用户和图书服务。"""

    def __init__(
        self,
        resolver: ServiceResolver,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 2.0,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 5.0,
        breakers: dict[str, CircuitBreaker] | None = None,
    ) -> None:
        self.balancer = RoundRobinBalancer(resolver)
        self.http_client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            # 修复 "Server disconnected without sending a response":
            # uvicorn 默认只保持 5 秒空闲的 keep-alive 连接，httpx 的连接池
            # 可能复用一条已经被对端悄悄关闭的旧连接，而 transport(retries=1)
            # 只对"根本连不上"生效，不覆盖这种情况。这里直接关闭长连接复用
            # （每次调用都开新连接），从根上避免这个竞态问题——调用频率不高，
            # 牺牲一点点连接建立开销换稳定性是值得的。
            limits=httpx.Limits(max_keepalive_connections=0),
        )
        self.breakers = breakers or {
            USER_SERVICE: CircuitBreaker(failure_threshold, recovery_timeout_seconds),
            BOOK_SERVICE: CircuitBreaker(failure_threshold, recovery_timeout_seconds),
        }

    async def close(self) -> None:
        """Close HTTP resources / 关闭 HTTP 资源。"""
        await self.http_client.aclose()

    def breaker_state(self, service_name: str) -> str:
        """Expose a breaker state for diagnostics / 返回熔断器诊断状态。"""
        return self.breakers[service_name].state.value

    async def request(
        self,
        service_name: str,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        selected_url: str | None = None,
    ) -> tuple[httpx.Response, str]:
        """Call one discovered instance / 调用一个已发现实例。"""
        breaker = self.breakers[service_name]
        try:
            breaker.before_call()
        except CircuitOpenError as error:
            raise ServiceCallError(
                503,
                "CIRCUIT_OPEN",
                f"{service_name} circuit is open; request degraded",
                service_name,
                math.ceil(error.retry_after_seconds),
            ) from error

        try:
            base_url = selected_url or self.balancer.select(service_name)
            response = await self.http_client.request(
                method,
                f"{base_url}/{path.lstrip('/')}",
                headers=headers,
            )
        except ServiceCallError:
            breaker.record_failure()
            raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as error:
            breaker.record_failure()
            raise ServiceCallError(
                503,
                "DOWNSTREAM_UNAVAILABLE",
                f"{service_name} call failed or timed out; request degraded",
                service_name,
            ) from error

        if response.status_code >= 500:
            breaker.record_failure()
            raise ServiceCallError(
                503,
                "DOWNSTREAM_UNAVAILABLE",
                f"{service_name} returned {response.status_code}; request degraded",
                service_name,
            )
        breaker.record_success()
        return response, base_url

    async def validate_user(self, user_id: str, authorization: str | None) -> dict[str, object]:
        """Validate a user through user-service / 通过用户服务验证用户。"""
        headers = {"X-User-Id": user_id}
        if authorization:
            headers["Authorization"] = authorization
        response, _ = await self.request(USER_SERVICE, "GET", f"/users/{user_id}", headers)
        if response.status_code == 404:
            raise ServiceCallError(404, "USER_NOT_FOUND", "User not found", USER_SERVICE)
        if response.status_code >= 400:
            raise ServiceCallError(
                response.status_code,
                "USER_VALIDATION_FAILED",
                response_detail(response, "User validation failed"),
                USER_SERVICE,
            )
        return response.json()

    async def get_book(self, book_id: int) -> tuple[dict[str, object], str]:
        """Validate a book through book-service / 通过图书服务验证图书。"""
        response, selected_url = await self.request(BOOK_SERVICE, "GET", f"/api/books/{book_id}")
        if response.status_code == 404:
            raise ServiceCallError(404, "BOOK_NOT_FOUND", "Book not found", BOOK_SERVICE)
        if response.status_code >= 400:
            raise ServiceCallError(
                response.status_code,
                "BOOK_VALIDATION_FAILED",
                response_detail(response, "Book validation failed"),
                BOOK_SERVICE,
            )
        return response.json(), selected_url

    async def borrow_book(self, book_id: int, selected_url: str) -> dict[str, object]:
        """Reserve book inventory through HTTP / 通过 HTTP 扣减图书库存。"""
        response, _ = await self.request(
            BOOK_SERVICE,
            "POST",
            f"/internal/books/{book_id}/borrow",
            selected_url=selected_url,
        )
        if response.status_code >= 400:
            raise ServiceCallError(
                response.status_code,
                "BOOK_BORROW_REJECTED",
                response_detail(response, "Book could not be borrowed"),
                BOOK_SERVICE,
            )
        return response.json()

    async def return_book(
        self,
        book_id: int,
        selected_url: str | None = None,
    ) -> dict[str, object]:
        """Restore book inventory through HTTP / 通过 HTTP 恢复图书库存。"""
        response, _ = await self.request(
            BOOK_SERVICE,
            "POST",
            f"/internal/books/{book_id}/return",
            selected_url=selected_url,
        )
        if response.status_code >= 400:
            raise ServiceCallError(
                response.status_code,
                "BOOK_RETURN_REJECTED",
                response_detail(response, "Book could not be returned"),
                BOOK_SERVICE,
            )
        return response.json()
