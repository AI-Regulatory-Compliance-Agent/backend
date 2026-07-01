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
    """Merge updates into existing session, preserving the original TTL."""
    import json
    key = f"session:{session_id}"
    existing = get_session(session_id) or {}
    existing.update(updates)
    
    ttl = redis_client.ttl(key)
    # ttl == -2: key doesn't exist; ttl == -1: key has no expiry set
    effective_ttl = ttl if ttl > 0 else 86400
    
    redis_client.setex(key, effective_ttl, json.dumps(existing))


def set_agent_progress(session_id: str, agent: str, status: str):
    """
    Track which agent is currently running.
    Called by each agent node when it starts and completes.
    """
    update_session(session_id, {
        "current_agent": agent,
        "agent_status": status
    })