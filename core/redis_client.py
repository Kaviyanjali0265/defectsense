import json
import os

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
STREAM_NAME = "defect-events"

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(REDIS_URL, decode_responses=True)
    return _client


def push_event(event: dict) -> str:
    """Push a sensor event to the Redis Stream. Returns the stream entry ID."""
    client = get_client()
    # XADD - Redis auto-generates ID as timestamp-sequence e.g. 1704067200000-0
    entry_id = client.xadd(STREAM_NAME, {"payload": json.dumps(event)})
    return entry_id


def read_events(
    last_id: str = "$", count: int = 10, block_ms: int = 1000
) -> list[dict]:
    """Read new events from the stream. Blocks up to block_ms if stream is empty."""
    client = get_client()
    results = client.xread(
        {STREAM_NAME: last_id},
        count=count,
        block=block_ms,
    )
    if not results:
        return []

    entries = []
    for _, messages in results:
        for entry_id, fields in messages:
            entries.append(
                {
                    "stream_id": entry_id,
                    "event": json.loads(fields["payload"]),
                }
            )
    return entries
