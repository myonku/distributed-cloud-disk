"""
在该文件中统一提供仓库实例或工厂方法，避免循环依赖。
"""

from kafka.kafka_client import KafkaClient
from repositories.redis_store import RedisManager


redis = RedisManager()
kafka = KafkaClient()
