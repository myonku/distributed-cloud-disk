from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterable
from dataclasses import dataclass
from typing import BinaryIO, overload
import asyncio
from datetime import timedelta

from minio import Minio
from minio.error import S3Error

from config import ProjectConfig


@dataclass
class PresignResult:
    url: str
    expires_in: int
    bucket: str
    object_key: str


class AsyncMinioClientWrapper:
    """
    MinIO 客户端最小异步封装（minio-async）
    - 面向在 async 端点中直接调用，避免线程池包装
    - 提供与同步版等价的能力：确保桶、预签名上传/下载、简单 put/remove（异步）
    - 端点选择：优先使用 config.minio.NODES 的首个节点，否则回退到 HOST/PORT

    连接生命周期：
    - 初始化阶段不触碰配置与连接
    - 显式调用 connect(cfg?) 建立连接；调用 close() 关闭连接
    """

    # 可由外部读取/设置的配置引用（实例将会覆盖此默认值）

    def __init__(self) -> None:
        # 仅保存配置引用，不执行连接
        self.cfg = None
        self._client: Minio | None = None
        self._default_bucket: str = ""
        self._sign_default: int = 3600

    async def connect(self, cfg: ProjectConfig):
        """建立与 MinIO 的连接（异步）
        - 可传入 cfg；若未传入则使用 self.cfg；两者都缺失会报错
        """
        self.cfg = cfg
        if cfg is None or cfg.minio is None:
            raise ValueError("MinIO 配置未提供")

        mcfg = cfg.minio
        # 选择端点：若提供 NODES 列表，则取首个作为默认端点
        if mcfg.NODES and len(mcfg.NODES) > 0:
            node = mcfg.NODES[0]
            endpoint = f"{node.HOST}:{node.PORT}"
            secure = node.SECURE
        else:
            # 兼容旧配置
            if not (mcfg.HOST and mcfg.PORT is not None):
                raise ValueError("MinIO HOST/PORT 必须提供")
            endpoint = f"{mcfg.HOST}:{mcfg.PORT}"
            secure = mcfg.SECURE

        client_kwargs: dict = {
            "endpoint": endpoint,
            "secure": secure,
        }
        if mcfg.ACCESS_KEY is not None:
            client_kwargs["access_key"] = mcfg.ACCESS_KEY
        if mcfg.SECRET_KEY is not None:
            client_kwargs["secret_key"] = mcfg.SECRET_KEY
        if mcfg.REGION is not None:
            client_kwargs["region"] = mcfg.REGION

        self._client = Minio(**client_kwargs)
        self._default_bucket = mcfg.DEFAULT_BUCKET or ""
        self._sign_default = int(mcfg.SIGN_EXPIRES_SECONDS)
        
        return self

    @property
    def client(self) -> Minio:
        if self._client is None:
            raise RuntimeError("MinIO 客户端未连接，请先调用 connect()")
        return self._client

    async def __aenter__(self) -> "AsyncMinioClientWrapper":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        """关闭底层 HTTP 客户端会话"""
        if self._client is not None:
            await self._client.close()
            self._client = None

    # 为兼容旧名称保留
    async def aclose(self) -> None:
        await self.close()

    async def ensure_bucket(self, bucket: str | None = None) -> bool:
        """确保 bucket 存在（不存在则创建）"""
        bucket = bucket or self._default_bucket
        if not bucket:
            raise ValueError("Bucket name required")
        try:
            client = self.client
            if not await client.bucket_exists(bucket):
                await client.make_bucket(bucket)
            return True
        except S3Error as e:
            raise Exception(f"Ensure bucket '{bucket}' failed: {e}") from e

    async def presign_put(
        self,
        object_key: str,
        bucket: str | None = None,
        expires_seconds: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> PresignResult:
        """生成对象 PUT 预签名 URL（异步）"""
        bucket = bucket or self._default_bucket
        if not bucket:
            raise ValueError("Bucket name required")
        expires = int(expires_seconds or self._sign_default)
        client = self.client
        url = await client.presigned_put_object(
            bucket_name=bucket,
            object_name=object_key,
            expires=timedelta(seconds=expires),
        )
        return PresignResult(
            url=url, expires_in=expires, bucket=bucket, object_key=object_key
        )

    async def presign_get(
        self,
        object_key: str,
        bucket: str | None = None,
        expires_seconds: int | None = None,
        params: dict[str, str] | None = None,
    ) -> PresignResult:
        """生成对象 GET 预签名 URL（异步）"""
        bucket = bucket or self._default_bucket
        if not bucket:
            raise ValueError("Bucket name required")
        expires = int(expires_seconds or self._sign_default)
        client = self.client
        url = await client.presigned_get_object(
            bucket_name=bucket,
            object_name=object_key,
            expires=timedelta(seconds=expires),
            response_headers=params,
        )
        return PresignResult(
            url=url, expires_in=expires, bucket=bucket, object_key=object_key
        )

    async def put_object(
        self,
        object_key: str,
        data: BinaryIO | bytes | AsyncIterable[bytes],
        length: int,
        content_type: str | None = None,
        bucket: str | None = None,
    ) -> str:
        """
        直接上传对象（异步；小/中文件直传场景）
        - data 可为 BinaryIO/bytes/AsyncIterable[bytes]
        - length 必须为要上传的总字节数
        返回 etag
        """
        bucket = bucket or self._default_bucket
        if not bucket:
            raise ValueError("Bucket name required")

        source: AsyncGenerator[bytes, None]
        if isinstance(data, (bytes, bytearray)):
            async def _gen_from_bytes(b: bytes) -> AsyncGenerator[bytes, None]:
                yield bytes(b)
            source = _gen_from_bytes(bytes(data))
        elif hasattr(data, "__aiter__"):
            # 已是 AsyncIterable[bytes]
            async def _gen_from_async_iter(ai: AsyncIterable[bytes]) -> AsyncGenerator[bytes, None]:
                async for chunk in ai:
                    yield chunk
            source = _gen_from_async_iter(data)  # type: ignore[arg-type]
        else:
            # 视为同步 BinaryIO，包装到线程池读取
            if not hasattr(data, "read"):
                raise TypeError("data 必须是 BinaryIO/bytes/AsyncIterable[bytes]")
            from typing import cast
            bio = cast(BinaryIO, data)
            loop = asyncio.get_running_loop()
            def _read_chunk() -> bytes:
                return bio.read(1024 * 1024)
            async def _gen_from_binaryio() -> AsyncGenerator[bytes, None]:
                while True:
                    chunk = await loop.run_in_executor(None, _read_chunk)
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray)):
                        raise TypeError("read() 必须返回 bytes")
                    yield bytes(chunk)
            source = _gen_from_binaryio()

        client = self.client
        result = await client.put_object(
            bucket_name=bucket,
            object_name=object_key,
            source=source,
            length=length,
            content_type=content_type or "application/octet-stream",
        )
        return result.etag

    async def remove_object(self, object_key: str, bucket: str | None = None) -> None:
        """删除对象（异步）"""
        bucket = bucket or self._default_bucket
        if not bucket:
            raise ValueError("Bucket name required")
        client = self.client
        await client.remove_object(bucket_name=bucket, object_name=object_key)
