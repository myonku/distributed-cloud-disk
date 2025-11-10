from pydantic import BaseModel, ConfigDict


class BucketEnsureResult(BaseModel):
    """MinIO 桶创建结果"""
    model_config = ConfigDict(strict=True)
    bucket: str
    exists: bool


class PresignedResult(BaseModel):
    """MinIO 预签名结果"""
    model_config = ConfigDict(strict=True)
    url: str
    expires_in: int
    object_key: str
    bucket: str
