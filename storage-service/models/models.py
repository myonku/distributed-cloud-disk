from typing import Literal
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID
from msgspec import Struct
from enum import Enum


class UploadSessionStatus(str, Enum):
    """上传会话状态枚举

    设计说明：
    - pending: 已创建（尚未开始分片上传，可能还未创建 MinIO Multipart）
    - uploading: 正在分片上传（部分分片已提交）
    - ready_to_merge: 分片全部提交，等待合并（CompleteMultipartUpload）
    - merged: 已合并完成，文件对象生成成功
    - aborted: 已主动/系统中止（需要清理 Multipart）
    """

    PENDING = "pending"
    UPLOADING = "uploading"
    READY_TO_MERGE = "ready_to_merge"
    MERGED = "merged"
    ABORTED = "aborted"


class BackendSessionCache(Struct, frozen=True):
    """后端会话缓存"""

    id: str
    user_id: str | None
    backend: Literal["storage"]
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
    backend: Literal["storage"]  # 当前服务标识
    client_pub_eph_b64: str  # 客户端临时公钥（Base64 原始 X25519 公钥）
    server_pub_b64: str  # 服务器（静态）公钥（Base64 或指纹字符串）
    server_nonce_b64: str  # 服务端随机数（Base64）
    created_at: float  # epoch 秒
    expires_at: float  # 过期（用于整体 TTL）
    verify_deadline_at: float  # confirm 最晚时间（秒级）


class ChunkReceipt(BaseModel):
    """存储块收据模型"""

    model_config = ConfigDict(from_attributes=True, strict=True)
    chunk_id: str
    upload_session_id: UUID
    index: int
    size: int
    checksum: str | None = None
    stored_at: datetime
    node_id: str


class ChunkStatus(BaseModel):
    """存储块状态模型"""

    model_config = ConfigDict(from_attributes=True, strict=True)
    chunk_id: str
    exists: bool
    node_id: str
    last_verified_at: datetime | None = None


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


class UploadSession(BaseModel):
    """大文件上传会话模型（业务层 + Multipart 关联）

    存储建议：MySQL/Postgres（行）或 KV（Redis 仅做短期加速），用于进度/状态查询。
    和对象存储的 Multipart Upload 通过 upload_id 建立关联。
    """

    model_config = ConfigDict(from_attributes=True, strict=True)
    id: UUID  # 业务会话 ID（对外暴露）
    owner_id: str
    tenant_id: str | None = None
    file_name: str
    content_type: str | None = None
    total_size: int  # 预计总大小（客户端声明）
    part_size: int  # 分片大小（用于 expected_parts 计算）
    expected_parts: int  # 预估分片数（total_size/part_size 向上取整）
    upload_id: str | None = None  # MinIO Multipart UploadId
    status: UploadSessionStatus = UploadSessionStatus.PENDING
    object_key: str | None = None  # 合并后生成的对象 key（按策略）
    bucket: str | None = None
    checksum: str | None = None  # 全文件哈希（客户端或合并后计算）
    created_at: datetime
    expires_at: datetime  # 会话过期（未完成则可自动 ABORT）
    merged_at: datetime | None = None
    aborted_at: datetime | None = None
    last_part_committed_at: datetime | None = None


class UploadPartCommit(BaseModel):
    """单个分片提交（commit）记录

    幂等：同一 (session_id, part_number) 重复写入不应报错；可用唯一索引。
    size/etag 可来自客户端回调或 ListParts 读取。
    """

    model_config = ConfigDict(from_attributes=True, strict=True)
    session_id: UUID
    part_number: int
    etag: str
    size: int
    committed_at: datetime
    checksum: str | None = None  # 可选：分片内容哈希（若客户端上传前已计算）


class FileMetadata(BaseModel):
    """文件最终元数据（合并后持久化）

    与对象存储中的物理对象一一对应。用于检索/权限控制/下载预签名生成。
    拆分建议：此模型可以放到独立的“元数据服务”中，只保留对象 key 与必要的检索字段。
    """

    model_config = ConfigDict(from_attributes=True, strict=True)
    file_id: UUID
    owner_id: str
    tenant_id: str | None = None
    object_key: str
    bucket: str
    size: int
    content_type: str | None = None
    sha256: str | None = None  # 全文件内容哈希（去重/校验）
    md5: str | None = None  # 若需要兼容或审计
    storage_class: str | None = None  # 预留：不同存储层/策略
    version: int | None = None  # 若支持版本管理
    created_at: datetime
    uploaded_at: datetime  # 对象实际完成（merged）时间
    deleted_at: datetime | None = None
    tags_json: str | None = None  # 复杂标签 JSON 字符串（可外置单独表）


class DownloadIntent(BaseModel):
    """下载意图记录（审计/统计）

    由生成预签名下载 URL 时创建，真正下载完成可结合访问日志或后续事件补充。
    """

    model_config = ConfigDict(from_attributes=True, strict=True)
    intent_id: UUID
    file_id: UUID
    user_id: str | None = None
    tenant_id: str | None = None
    object_key: str
    bucket: str
    generated_at: datetime
    expires_at: datetime
    downloaded_at: datetime | None = None  # 确认下载完成时间（通过回调/日志聚合）
    client_ip: str | None = None


class BucketProvision(BaseModel):
    """桶预配与策略记录

    用于追踪某租户/用户的桶创建与策略变更历史，便于审计与对账。
    可放入元数据服务，存储无强实时性需求。
    """

    model_config = ConfigDict(from_attributes=True, strict=True)
    bucket: str
    tenant_id: str | None = None
    user_id: str | None = None
    versioning_enabled: bool | None = None
    lifecycle_json: str | None = None  # 生命周期策略（原始 JSON）
    quota_bytes: int | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ObjectUsageSnapshot(BaseModel):
    """对象用量快照（离线或异步统计结果）

    定期任务生成，供快速查询；细粒度实时统计可另设流式方案。
    """

    model_config = ConfigDict(from_attributes=True, strict=True)
    snapshot_id: UUID
    generated_at: datetime
    tenant_id: str | None = None
    total_files: int
    total_bytes: int
    hot_files: int | None = None  # 访问频繁的文件数量（可选）
    cold_bytes: int | None = None  # 冷数据字节数（归档层）
