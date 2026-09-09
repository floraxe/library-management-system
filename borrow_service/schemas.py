"""Borrow API schemas / 借阅 API 数据结构。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BorrowCreate(BaseModel):
    """Validate a borrow request / 校验借书请求。"""

    book_id: int = Field(gt=0)


class BorrowResponse(BaseModel):
    """Expose a borrow record / 返回借阅记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    book_id: int
    status: Literal["borrowed", "returning", "returned"]
    borrowed_at: datetime
    returned_at: datetime | None


class HealthResponse(BaseModel):
    """Expose borrow-service health / 返回借阅服务健康状态。"""

    status: str
    service: str
    port: int
    breakers: dict[str, str]
