from qdrant_client import QdrantClient
from app.config import get_settings

settings = get_settings()

if settings.qdrant_host.startswith("http"):
    # Cloud mode — use URL directly with API key
    if not settings.qdrant_api_key:
        raise ValueError(
            "QDRANT_API_KEY must be set when using Qdrant cloud "
            f"(qdrant_host={settings.qdrant_host!r}). "
            "Set the QDRANT_API_KEY environment variable."
        )
    qdrant_client = QdrantClient(
        url=settings.qdrant_host,
        api_key=settings.qdrant_api_key,
    )
else:
    # Local mode — use host:port
    qdrant_client = QdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
    )
