from qdrant_client import QdrantClient
from app.config import get_settings

settings = get_settings()

qdrant_client = QdrantClient(
    host=settings.qdrant_host,
    port=settings.qdrant_port
)