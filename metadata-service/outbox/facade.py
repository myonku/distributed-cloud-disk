from kafka.models import encode_envelope, new_envelope
from outbox.service import OutboxService
from kafka.publisher import KafkaPublisher

# 可靠事件 Topic
TOPIC_UPLOAD_EVENTS = "dcd.upload.events.v1"
# 非可靠（审计示例）
TOPIC_AUDIT_EVENTS = "dcd.audit.events.v1"


class DomainEventFacade:
    """
    同时提供：
      - 可靠（走 Outbox）
      - 非可靠（直接发）
    的统一入口，调用方无需关心实现细节。
    """

    def __init__(
        self,
        *,
        outbox: OutboxService,
        publisher: KafkaPublisher,
        source: str,
    ) -> None:
        self.outbox = outbox
        self.publisher = publisher
        self.source = source

    async def emit_upload_session_created(
        self,
        *,
        upload_session_id: str,
        owner_id: str,
        file_name: str,
        size: int,
        chunk_size: int,
        placement_policy: str,
        tx=None,
        trace_id: str | None = None,
        tenant_id: str | None = None,
    ):
        """发布 创建上传会话 事件（可靠，通过 Outbox）"""
        env = new_envelope(
            type="UPLOAD_SESSION_CREATED",
            aggregate_type="upload_session",
            aggregate_id=upload_session_id,
            source=self.source,
            payload={
                "upload_session_id": upload_session_id,
                "owner_id": owner_id,
                "file_name": file_name,
                "size": size,
                "chunk_size": chunk_size,
                "placement_policy": placement_policy,
            },
        )
        # 只保存，派发由 dispatcher 异步完成
        await self.outbox.save_reliable(
            envelope=env,
            topic=TOPIC_UPLOAD_EVENTS,
            key=upload_session_id.encode(),
            tx=tx,
            trace_id=trace_id,
            tenant_id=tenant_id,
        )

    async def publish_request_audit(
        self,
        *,
        trace_id: str,
        route: str,
        method: str,
        user_id: str | None,
        status: int,
    ):
        """发布 请求审计 事件（非可靠，直接发）"""
        env = new_envelope(
            type="REQUEST_AUDIT",
            aggregate_type="http_request",
            aggregate_id=trace_id,
            source=self.source,
            payload={
                "trace_id": trace_id,
                "route": route,
                "method": method,
                "user_id": user_id,
                "status": status,
            },
        )
        await self.publisher.publish(
            topic=TOPIC_AUDIT_EVENTS,
            value=encode_envelope(env),
            key=trace_id.encode(),
        )
