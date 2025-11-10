from typing import Literal
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID
from msgspec import Struct


class BackendSessionCache(Struct, frozen=True):
    id: str
    user_id: str | None
    backend: str
    client_pub_eph: str
    server_pub_eph: str
    device_printer: str
    key_fpr: str
    claims_hash: str  # 对绑定的基础 claims (user_id, roles, tenant, cred_level) 做哈希
    cred_level: int
    roles: str  # 逗号分隔
    tenant_id: str | None
    established_at: float
    claims_refreshed_at: float
    expires_at: float


class User(BaseModel):
    """用户模型"""
    model_config = ConfigDict(from_attributes=True, strict=True)
    id: UUID
    username: str
    email: str
    alias: str | None = None
    pwdhash: str
    public_key: str
    status: Literal["active", "inactive", "banned"]
    role: Literal["user", "admin", "superadmin"]
    created_at: datetime
    last_login_at: datetime | None = None


class UserProfile(BaseModel):
    """用户资料模型"""
    model_config = ConfigDict(from_attributes=True, strict=True)
    user_id: UUID
    display_name: str
    avatar_url: str | None = None
    bio: str | None = None
