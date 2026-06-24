import redis
from app.config import get_settings

settings = get_settings()

redis_client = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    decode_responses=True      # returns strings not bytes
)


def set_session(session_id: str, data: dict, ttl: int = 86400):
    """Store session data. TTL default 24 hours."""
    import json
    redis_client.setex(
        f"session:{session_id}",
        ttl,
        json.dumps(data)
    )


def get_session(session_id: str) -> dict | None:
    import json
    data = redis_client.get(f"session:{session_id}")
    if data:
        return json.loads(data)
    return None


def update_session(session_id: str, updates: dict):
    """Merge updates into existing session."""
    existing = get_session(session_id) or {}
    existing.update(updates)
    set_session(session_id, existing)


def set_agent_progress(session_id: str, agent: str, status: str):
    """
    Track which agent is currently running.
    Called by each agent node when it starts and completes.
    """
    update_session(session_id, {
        "current_agent": agent,
        "agent_status": status
    })