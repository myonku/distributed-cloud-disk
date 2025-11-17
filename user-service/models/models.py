from typing import Literal
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID
from msgspec import Struct

class BackendSessionCache(Struct, frozen=True):
    """后端会话缓存"""

    id: str
    user_id: str | None
    backend: Literal["user"]
    client_pub_eph_b64: str  # 客户端临时公钥（Base64）
    server_pub_b64: str  # 服务器（静态）公钥（Base64 或指纹）
    shared_secret_fpr: str  # 指纹（便于审计）
    verified: bool  # 是否已完成 confirm
    # 授权绑定（按需刷新）
    claims_hash: str
    cred_level: int
    roles: str  # 逗号分隔，复杂时可换 JSON 字符串
    tenant_id: str | None  # 绑定的租户 ID（多租户场景）
    established_at: float
    claims_refreshed_at: float
    expires_at: float


class TemporaryHandshake(Struct, frozen=True):
    """
    临时握手模型：用于 init 和 confirm 之间的短期状态，存 Redis
    不存任何对称密钥与服务端临时私钥
    """

    id: str  # backendSessionId (UUID)
    backend: Literal["user"]  # 当前服务标识
    client_pub_eph_b64: str  # 客户端临时公钥（Base64 原始 X25519 公钥）
    server_pub_b64: str  # 服务器（静态）公钥（Base64 或指纹字符串）
    server_nonce_b64: str  # 服务端随机数（Base64）
    created_at: float  # epoch 秒
    expires_at: float  # 过期（用于整体 TTL）
    verify_deadline_at: float  # confirm 最晚时间（秒级）


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


class ServiceInstance(Struct, frozen=True):
    """
    注册到 etcd 的实例信息（值）
    """

    id: str
    name: str
    endpoint: str  # http://host:port 或 grpc://host:port
    zone: str | None
    version: str | None
    weight: int  # 基础权重
    tags: list[str]  # ["primary","canary","bulk"]
    meta_json: str  # 复杂结构外部再解析
    heartbeat_at: float  # 最近心跳（监控）


class ServiceSnapshot(Struct, frozen=True):
    """
    从 etcd watch 得到的某服务的快照（缓存到内存，供路由使用）
    """

    name: str
    instances: list[ServiceInstance]
    revision: int
