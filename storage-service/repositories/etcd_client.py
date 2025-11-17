import asyncio
import random
from collections.abc import Callable, Awaitable
from typing import Any, cast

import grpc
from msgspec import json

from config import ProjectConfig
from models.models import ServiceInstance
from etcd3 import etcdrpc as _etcdrpc

# 将 etcdrpc 标注为 Any，避免由缺失类型信息引起的静态检查误报
etcdrpc: Any = cast(Any, _etcdrpc)


def _prefix_range_end(prefix: str) -> bytes:
    """计算 etcd Range 的 range_end 以实现前缀查询。

    方法：对最后一个字节 +1；若全 0xFF 则返回单字节 0x00 作为最小上界。
    参考 etcd 官方前缀范围约定。
    """
    b = bytearray(prefix.encode())
    for i in range(len(b) - 1, -1, -1):
        if b[i] < 0xFF:
            b[i] += 1
            return bytes(b[: i + 1])
    return b"\x00"


class EtcdAsyncClient:
    """原生异步 etcd v3 客户端（基于 grpc.aio）

    仅实现本项目需要的最小接口：
      - connect
      - put_with_lease
      - keepalive_forever
      - delete
      - get_prefix
      - watch_prefix

    依赖: grpcio, etcd3 (提供 etcdrpc 代码)。
    后续可扩展: 重连/错误分类/metrics/compaction 恢复。
    """

    async def connect(self, cfg: ProjectConfig):
        """建立 gRPC 连接并初始化 stubs。"""
        etcd_cfg = cfg.etcd
        assert etcd_cfg and etcd_cfg.HOSTS, "Etcd 配置缺失 HOSTS"
        self.namespace = etcd_cfg.NAMESPACE.rstrip("/")
        host_port = etcd_cfg.HOSTS[0]
        if ":" in host_port:
            host, port = host_port.split(":", 1)
        else:
            host, port = host_port, "2379"

        target = f"{host}:{port}"
        if etcd_cfg.TLS_ENABLED:
            root_bytes = None
            cert_chain_bytes = None
            key_bytes = None
            if etcd_cfg.CA_CERT:
                try:
                    with open(etcd_cfg.CA_CERT, "rb") as f:
                        root_bytes = f.read()
                except Exception:
                    root_bytes = None
            if etcd_cfg.CERT_FILE and etcd_cfg.KEY_FILE:
                try:
                    with open(etcd_cfg.CERT_FILE, "rb") as f:
                        cert_chain_bytes = f.read()
                    with open(etcd_cfg.KEY_FILE, "rb") as f:
                        key_bytes = f.read()
                except Exception:
                    cert_chain_bytes = None
                    key_bytes = None
            creds = grpc.ssl_channel_credentials(
                root_certificates=root_bytes,
                private_key=key_bytes,
                certificate_chain=cert_chain_bytes,
            )
            self._channel = grpc.aio.secure_channel(target, creds)
        else:
            self._channel = grpc.aio.insecure_channel(target)

        # 初始化 stubs
        self._kv_stub = etcdrpc.KVStub(self._channel)
        self._lease_stub = etcdrpc.LeaseStub(self._channel)
        self._watch_stub = etcdrpc.WatchStub(self._channel)
        self._connected = True

    async def _grant_or_reuse_lease(self, ttl: int) -> int:
        """创建或重用租约，返回租约 ID。"""
        if self._lease_id is not None:
            return self._lease_id
        assert self._lease_stub, "Lease stub 未初始化"
        resp = await self._lease_stub.LeaseGrant(etcdrpc.LeaseGrantRequest(TTL=ttl))
        self._lease_id = resp.ID
        assert self._lease_id is not None
        return self._lease_id

    async def put_with_lease(self, key: str, value_bytes: bytes, ttl: int) -> None:
        """写入 key 并绑定租约（如不存在则创建新租约）。"""
        assert self._kv_stub, "KV stub 未初始化"
        lease_id = await self._grant_or_reuse_lease(ttl)
        await self._kv_stub.Put(
            etcdrpc.PutRequest(key=key.encode(), value=value_bytes, lease=lease_id)
        )

    async def keepalive_forever(self, ttl: int, stop_event: asyncio.Event):
        """保持租约存活（流式 keepalive）。"""
        if self._lease_id is None:
            return

        async def req_gen():
            while not stop_event.is_set():
                yield etcdrpc.LeaseKeepAliveRequest(ID=self._lease_id)
                await asyncio.sleep(ttl / 2)

        # 消费响应，忽略具体内容；若需要可记录 latency / remaining TTL
        try:
            assert self._lease_stub, "Lease stub 未初始化"
            call = self._lease_stub.LeaseKeepAlive(req_gen())
            async for _ in call:  # noqa: F841
                if stop_event.is_set():
                    break
        except Exception:
            # 发生异常后退出，外层可重启 keepalive 任务
            pass

    async def delete(self, key: str):
        """删除指定 key。"""
        assert self._kv_stub, "KV stub 未初始化"

        await self._kv_stub.DeleteRange(etcdrpc.DeleteRangeRequest(key=key.encode()))

    async def get_prefix(self, prefix: str) -> list[tuple[str, bytes]]:
        """列出前缀下所有 KV。"""
        assert self._kv_stub, "KV stub 未初始化"
        range_end = _prefix_range_end(prefix)
        resp = await self._kv_stub.Range(
            etcdrpc.RangeRequest(key=prefix.encode(), range_end=range_end)
        )
        out: list[tuple[str, bytes]] = []
        for kv in resp.kvs:
            try:
                out.append((kv.key.decode(), kv.value))
            except Exception:
                continue
        return out

    async def get_prefix_with_revision(
        self, prefix: str
    ) -> tuple[int, list[tuple[str, bytes]]]:
        """返回 (etcd_revision, [(key,value_bytes)...])，用于避免加载与 watch 之间的竞态。"""
        assert self._kv_stub, "KV stub 未初始化"
        range_end = _prefix_range_end(prefix)
        resp = await self._kv_stub.Range(
            etcdrpc.RangeRequest(key=prefix.encode(), range_end=range_end)
        )
        header = getattr(resp, "header", None)
        rev = int(getattr(header, "revision", 0) or 0)
        out: list[tuple[str, bytes]] = []
        for kv in resp.kvs:
            try:
                out.append((kv.key.decode(), kv.value))
            except Exception:
                continue
        return rev, out

    async def watch_prefix(
        self,
        prefix: str,
        callback: Callable[[str, bytes | None], Awaitable[None]],
        stop_event: asyncio.Event,
        start_revision: int = 0,
    ):
        """监听前缀，回调 put/delete 事件，并在断流/压缩后自恢复。

        start_revision: 指定起始修订（通常为 初始 Range 的 revision + 1）。
        """
        assert self._watch_stub, "Watch stub 未初始化"
        range_end = _prefix_range_end(prefix)

        next_revision: int = start_revision if start_revision > 0 else 0
        backoff = 0.2
        backoff_max = 5.0

        while not stop_event.is_set():
            create_req = etcdrpc.WatchRequest(
                create_request=etcdrpc.WatchCreateRequest(
                    key=prefix.encode(),
                    range_end=range_end,
                    start_revision=next_revision if next_revision > 0 else 0,
                    filters=[],
                )
            )

            async def req_gen():
                yield create_req
                while not stop_event.is_set():
                    await asyncio.sleep(1)

            try:
                stream = self._watch_stub.Watch(req_gen())
                backoff = 0.2
                async for resp in stream:
                    if stop_event.is_set():
                        break

                    # 压缩恢复
                    cr = int(getattr(resp, "compact_revision", 0) or 0)
                    if cr > 0 and (next_revision == 0 or next_revision <= cr):
                        next_revision = cr + 1
                        break

                    if getattr(resp, "canceled", False):
                        if cr > 0 and (next_revision == 0 or next_revision <= cr):
                            next_revision = cr + 1
                        break

                    for ev in getattr(resp, "events", []) or []:
                        etype = getattr(ev, "type", 0)
                        kv = getattr(ev, "kv", None)
                        if not kv:
                            continue
                        key_s = (
                            kv.key.decode()
                            if isinstance(kv.key, (bytes, bytearray))
                            else str(kv.key)
                        )
                        if etype == 0:
                            await callback(key_s, kv.value)
                        elif etype == 1:
                            await callback(key_s, None)

                        mr = int(getattr(kv, "mod_revision", 0) or 0)
                        if mr >= next_revision:
                            next_revision = mr + 1

            except grpc.aio.AioRpcError:
                pass
            except Exception:
                pass

            if stop_event.is_set():
                break
            await asyncio.sleep(backoff + random.random() * 0.2)
            backoff = min(backoff * 2, backoff_max)

    async def close(self):
        """关闭连接，释放资源。"""
        if self._channel:
            await self._channel.close()
        self._connected = False
        self._lease_id = None
        self._kv_stub = None
        self._lease_stub = None
        self._watch_stub = None


def build_service_key(ns: str, name: str, instance_id: str) -> str:
    """生成服务实例的 etcd 键"""
    return f"{ns}/services/{name}/{instance_id}"


def build_prefix(ns: str, name: str) -> str:
    """生成服务前缀"""
    return f"{ns}/services/{name}/"


def encode_instance(si: ServiceInstance) -> bytes:
    return json.encode(si)


def decode_instance(b: bytes) -> ServiceInstance:
    return json.decode(b, type=ServiceInstance)
