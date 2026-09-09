"""Book API schemas / 图书 API 数据结构。"""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BookCreate(BaseModel):
    """Validate a new book / 校验新增图书。"""

    title: str = Field(min_length=1, max_length=200)
    author: str = Field(min_length=1, max_length=120)
    isbn: str = Field(min_length=3, max_length=32)
    description: str | None = Field(default=None, max_length=2000)
    total_copies: int = Field(default=1, ge=0, le=1_000_000)

    @field_validator("title", "author", "isbn", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        """Trim required text fields / 清理必填文本字段。"""
        return value.strip() if isinstance(value, str) else value


class BookUpdate(BaseModel):
    """Validate a partial book update / 校验图书部分更新。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    author: str | None = Field(default=None, min_length=1, max_length=120)
    isbn: str | None = Field(default=None, min_length=3, max_length=32)
    description: str | None = Field(default=None, max_length=2000)
    total_copies: int | None = Field(default=None, ge=0, le=1_000_000)

    @field_validator("title", "author", "isbn", mode="before")
    @classmethod
    def strip_updated_text(cls, value: object) -> object:
        """Trim updated text fields / 清理更新文本字段。"""
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        """Require a useful partial update / 要求有效的部分更新。"""
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        required_fields = {"title", "author", "isbn", "total_copies"}
        if any(getattr(self, name) is None for name in self.model_fields_set & required_fields):
            raise ValueError("required book fields cannot be null")
        return self


class BookResponse(BaseModel):
    """Expose a stored book / 返回已存储图书。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    author: str
    isbn: str
    description: str | None
    total_copies: int
    available_copies: int
    created_at: datetime
    updated_at: datetime


class InventoryResponse(BaseModel):
    """Expose an inventory mutation / 返回库存操作结果。"""

    book_id: int
    total_copies: int
    available_copies: int


class HealthResponse(BaseModel):
    """Expose instance health / 返回实例健康状态。"""

    status: str
    service: str
    instance_id: str
    port: int
