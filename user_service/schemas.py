"""API request and response schemas / API 请求与响应结构。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_username(value: object) -> object:
    """Normalize string usernames / 标准化字符串用户名。"""
    return value.strip().lower() if isinstance(value, str) else value


class RegisterRequest(BaseModel):
    """Validate user registration input / 校验用户注册输入。"""

    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[a-z0-9_.-]+$",
    )
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_registered_username(cls, value: object) -> object:
        """Normalize the registered username / 标准化注册用户名。"""
        return normalize_username(value)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        """Trim and lowercase an email / 去除邮箱空格并转为小写。"""
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def validate_email_shape(cls, value: str) -> str:
        """Check a basic email shape / 检查基本邮箱格式。"""
        if value.count("@") != 1:
            raise ValueError("email must contain one @ character")
        local_part, domain = value.split("@")
        if not local_part or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("email must contain a valid local part and domain")
        return value


class LoginRequest(BaseModel):
    """Validate login credentials / 校验登录凭据。"""

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_login_username(cls, value: object) -> object:
        """Normalize the login username / 标准化登录用户名。"""
        return normalize_username(value)


class UserResponse(BaseModel):
    """Expose safe user fields / 仅公开安全的用户字段。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: str
    created_at: datetime


class TokenResponse(BaseModel):
    """Describe a successful login token / 描述登录成功令牌。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(gt=0)


class HealthResponse(BaseModel):
    """Describe service health / 描述服务健康状态。"""

    status: str
    service: str
