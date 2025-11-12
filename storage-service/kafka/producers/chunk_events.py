import time, uuid
from collections.abc import Mapping
from aiokafka.structs import RecordMetadata
from msgspec import json

from repositories.kafka_client import KafkaClient
from ..models import EventEnvelope, ChunkReceived, encode_envelope

TOPIC_CHUNK_EVENTS = "dcd.chunk.events.v1"


class ChunkEventProducer:
    """存储节点分片事件生产者"""

    def __init__(self, kc: KafkaClient) -> None:
        self.kc = kc

    async def publish_chunk_received(
        self,
        upload_session_id: str,
        chunk_id: str,
        index: int,
        size: int,
        node_id: str,
        checksum: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> RecordMetadata:
        payload = ChunkReceived(
            upload_session_id=upload_session_id,
            chunk_id=chunk_id,
            index=index,
            size=size,
            node_id=node_id,
            checksum=checksum,
        )
        env = EventEnvelope(
            event_id=str(uuid.uuid4()),
            type="CHUNK_RECEIVED",
            version=1,
            ts=time.time(),
            aggregate_type="chunk",
            aggregate_id=chunk_id,
            source="storage-service",
            headers=dict(headers or {}),
            payload=json.decode(json.encode(payload)),
        )
        key = chunk_id.encode()
        prod = self.kc.get_producer()
        md = await prod.send_and_wait(
            TOPIC_CHUNK_EVENTS,
            value=encode_envelope(env),
            key=key,
            headers=[(k, v.encode()) for k, v in env.headers.items()],
        )
        return md
