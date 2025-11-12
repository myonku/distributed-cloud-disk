import uuid, time
from collections.abc import Mapping
from aiokafka.structs import RecordMetadata
from msgspec import json
from kafka.models import EventEnvelope, UploadSessionCreated, encode_envelope
from repositories.kafka_client import KafkaClient

TOPIC_UPLOAD_EVENTS = "dcd.upload.events.v1"


class UploadEventProducer:
    """上传域事件生产者"""

    def __init__(self, kc: KafkaClient) -> None:
        self.kc = kc

    async def publish_upload_session_created(
        self,
        upload_session_id: str,
        owner_id: str,
        file_name: str,
        size: int,
        chunk_size: int,
        placement_policy: str,
        headers: Mapping[str, str] | None = None,
    ) -> RecordMetadata:
        payload = UploadSessionCreated(
            upload_session_id=upload_session_id,
            owner_id=owner_id,
            file_name=file_name,
            size=size,
            chunk_size=chunk_size,
            placement_policy=placement_policy,
        )
        env = EventEnvelope(
            event_id=str(uuid.uuid4()),
            type="UPLOAD_SESSION_CREATED",
            version=1,
            ts=time.time(),
            aggregate_type="upload_session",
            aggregate_id=upload_session_id,
            source="metadata-service",
            headers=dict(headers or {}),
            payload=json.decode(json.encode(payload)),  # 转 dict（保持稳定结构）
        )
        key = upload_session_id.encode()
        prod = self.kc.get_producer()
        md = await prod.send_and_wait(
            TOPIC_UPLOAD_EVENTS,
            value=encode_envelope(env),
            key=key,
            headers=[(k, v.encode()) for k, v in env.headers.items()],
        )
        return md
