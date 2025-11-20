from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID
from msgspec import Struct


class BackendSessionCache(Struct, frozen=True):
    """后端会话缓存"""

    id: str
    user_id: str | None
    backend: Literal["metadata"]
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
    backend: Literal["metadata"]  # 当前服务标识
    client_pub_eph_b64: str  # 客户端临时公钥（Base64 原始 X25519 公钥）
    server_pub_b64: str  # 服务器（静态）公钥（Base64 或指纹字符串）
    server_nonce_b64: str  # 服务端随机数（Base64）
    created_at: float  # epoch 秒
    expires_at: float  # 过期（用于整体 TTL）
    verify_deadline_at: float  # confirm 最晚时间（秒级）


# ========= 目录与文件逻辑模型 =========


class DirectoryEntry(BaseModel):
    """逻辑目录节点。
    - parent_id 为 None 表示根目录（或多租户下的虚拟根）。
    - full_path 便于快速查询（可维护 path 索引或前缀查询）。
    """

    model_config = ConfigDict(from_attributes=True, strict=True)
    dir_id: UUID
    tenant_id: str | None = None
    parent_id: UUID | None = None
    name: str
    full_path: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    tags_json: str | None = None  # 可扩展目录标签
    acl_json: str | None = None  # 权限策略（后续可拆表）


class FileEntry(BaseModel):
    """文件逻辑条目（不含版本具体信息）。指向当前有效版本。
    - directory_id 指向所属目录（可为 None 表示根）。
    - current_version_id 更新后指向最新版本；软删通过 deleted_at。
    """

    model_config = ConfigDict(from_attributes=True, strict=True)
    file_id: UUID
    tenant_id: str | None = None
    owner_id: str
    directory_id: UUID | None
    name: str
    full_path: str
    size: int
    current_version_id: UUID | None
    is_directory: bool = False  # 兼容统一列表接口（目录/文件混排）
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    tags_json: str | None = None  # 文件标签
    acl_json: str | None = None  # 权限策略（后续拆分）


class FileVersion(BaseModel):
    """文件版本记录（指向存储层对象）。
    - object_key / bucket 由 storage-service 返回或映射生成。
    - hash_sha256 用于内容地址/去重校验。
    - manifest_json 用于高级场景（分片清单、段信息、加密材料等）。
    """

    model_config = ConfigDict(from_attributes=True, strict=True)
    version_id: UUID
    file_id: UUID
    object_key: str
    bucket: str
    size: int
    hash_sha256: str | None = None
    hash_md5: str | None = None
    storage_class: str | None = None
    manifest_json: str | None = None
    encryption_meta_json: str | None = None  # 若端到端加密，存密钥包装信息
    created_at: datetime
    committed_at: datetime | None = None
    deleted_at: datetime | None = None
    tags_json: str | None = None


class FileMetadataLight(BaseModel):
    """轻量文件元数据视图（聚合 FileEntry + 当前版本关键字段）。
    用于列表/检索接口返回。
    """

    model_config = ConfigDict(from_attributes=True, strict=True)
    file_id: UUID
    name: str
    full_path: str
    directory_id: UUID | None
    size: int
    current_version_id: UUID | None
    bucket: str | None = None
    object_key: str | None = None
    content_type: str | None = None
    hash_sha256: str | None = None
    storage_class: str | None = None
    is_directory: bool
    updated_at: datetime
    deleted_at: datetime | None = None
    tenant_id: str | None = None
    owner_id: str
    tags_json: str | None = None


# ========= 上传会话（逻辑层） =========


class UploadSessionPhase(str, Enum):
    INIT = "init"  # 初始创建，尚未在存储层建立
    STORAGE_ALLOCATED = "storage_allocated"  # 已在 storage-service 建立底层会话
    RECEIVING_PARTS = "receiving_parts"  # Multipart 过程中
    READY_TO_FINALIZE = "ready_to_finalize"  # 所有必要 part 已确认（或单文件已上传）
    FINALIZING = "finalizing"  # 正在确认与合并（等待 storage merge 完成）
    COMMITTED = "committed"  # 元数据已写入版本记录
    ABORTED = "aborted"


class UploadSessionMeta(BaseModel):
    """逻辑上传会话（协调 storage-service 的底层 UploadSession）。

    字段说明：
    - storage_session_id: 底层存储会话 ID（storage-service 创建后回填）。
    - expected_parts: 预估需要的 part 数（可选，单文件则为 1）。
    - committed_parts: 已确认的 part 数（由事件或轮询更新）。
    - phase: UploadSessionPhase，决定是否可以 finalize。
    - object_key_temp: 临时对象 key（storage-service 在 merge 后会返回最终 key）。
    """

    model_config = ConfigDict(from_attributes=True, strict=True)
    upload_session_id: UUID
    file_id: UUID
    owner_id: str
    tenant_id: str | None = None
    file_name: str
    size: int
    chunk_size: int
    storage_strategy: str | None = None  # single | multipart | custom
    storage_session_id: str | None = None
    expected_parts: int | None = None
    committed_parts: int = 0
    phase: UploadSessionPhase
    object_key_temp: str | None = None
    bucket: str | None = None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
    aborted_at: datetime | None = None
    finalize_requested_at: datetime | None = None
    committed_version_id: UUID | None = None
    tags_json: str | None = None


class UploadPartLogical(BaseModel):
    """逻辑层记录某个 part 的接收状态（非必须；可以只依赖事件聚合）。
    - etag/size 从 storage-service 提交 part 时带回。
    """

    model_config = ConfigDict(from_attributes=True, strict=True)
    upload_session_id: UUID
    index: int
    etag: str | None = None
    size: int | None = None
    received_at: datetime
    committed_at: datetime | None = None
    checksum: str | None = None
    state: Literal["received", "committed", "skipped"]


# ========= 下载意图 =========

class DownloadIntent(BaseModel):
    """下载意图（逻辑层权限与路径校验后生成）。
    - presign_url: 若需要直接获取最终预签名 URL（可通过 storage-service 或 MinIO）。
    - scope: download | head | range
    """

    model_config = ConfigDict(from_attributes=True, strict=True)
    file_id: UUID
    version_id: UUID
    bucket: str
    object_key: str
    size: int
    content_type: str | None = None
    hash_sha256: str | None = None
    scope: str
    presign_url: str | None = None
    expires_at: datetime
    generated_at: datetime


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
