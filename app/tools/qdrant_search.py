"""
Qdrant Search Tool — RAG retrieval for regulation chunks.

This is the primary knowledge retrieval tool used by 3 of the 5 agent nodes:
  - regulation_identifier (Node 1): finds which regulations are relevant
  - gap_analysis (Node 2): fetches detailed clauses per regulation
  - remediation (Node 4): fetches specific sections for fix recommendations

How it works:
  1. Takes a natural language query (e.g., "payment data processing requirements")
  2. Embeds it using SentenceTransformer all-MiniLM-L6-v2 (384 dimensions)
  3. Searches Qdrant "regulations" collection using cosine similarity
  4. Optionally filters by regulation_name for targeted searches
  5. Returns top-k matching chunks with text and metadata

The embedding model is loaded ONCE at module level and reused across
all calls to avoid repeated loading (the model is ~80MB in memory).

Qdrant payload structure per chunk (set during ingestion):
  chunk_id, regulation_name, source_file, page_number, text, token_count
"""

from sentence_transformers import SentenceTransformer
from qdrant_client.models import Filter, FieldCondition, MatchValue
from app.qdrant_client import qdrant_client
from app.config import get_settings

settings = get_settings()

# ── Load Embedding Model ────────────────────────────────────
# Loaded once at module import time. Same model used during ingestion
# to ensure query embeddings match document embeddings.
# Model: all-MiniLM-L6-v2 → 384-dimensional vectors
_embedding_model = SentenceTransformer(settings.embedding_model)


def search_regulations(
    query: str,
    regulation_name: str | None = None,
    top_k: int = 5
) -> list[dict]:
    """
    Search the Qdrant regulations collection using semantic similarity.

    Args:
        query: Natural language search query. This gets embedded and
               compared against all stored regulation chunks.
        regulation_name: Optional filter to search within a specific
                        regulation (e.g., "DPDP Act", "GDPR").
                        If None, searches across ALL regulations.
        top_k: Number of top results to return. Default 5.
               Higher values give more context but cost more tokens
               when fed into the LLM prompt.

    Returns:
        List of dicts, each containing:
          - text: the actual chunk text (regulation content)
          - regulation_name: which regulation this chunk is from
          - source_file: original PDF filename
          - page_number: page in the original PDF
          - chunk_id: unique identifier for this chunk
          - score: cosine similarity score (0-1, higher = more relevant)

    Example:
        >>> results = search_regulations("payment data processing")
        >>> results[0]["text"]
        "Section 4(1): Every data fiduciary shall process personal data..."
        >>> results[0]["regulation_name"]
        "DPDP Act"
    """

    # Step 1: Embed the query using the same model used during ingestion
    query_vector = _embedding_model.encode(query).tolist()

    # Step 2: Build optional filter for specific regulation
    search_filter = None
    if regulation_name:
        # Filter narrows search to chunks from one regulation only.
        # Used by gap_analysis and remediation to get specific clauses.
        search_filter = Filter(
            must=[
                FieldCondition(
                    key="regulation_name",
                    match=MatchValue(value=regulation_name)
                )
            ]
        )

    # Step 3: Search Qdrant with cosine similarity
    results = qdrant_client.search(
        collection_name=settings.qdrant_collection,
        query_vector=query_vector,
        query_filter=search_filter,
        limit=top_k
    )

    # Step 4: Format results into clean dicts for agent consumption
    formatted = []
    for hit in results:
        formatted.append({
            "text": hit.payload.get("text", ""),
            "regulation_name": hit.payload.get("regulation_name", ""),
            "source_file": hit.payload.get("source_file", ""),
            "page_number": hit.payload.get("page_number", 0),
            "chunk_id": hit.payload.get("chunk_id", ""),
            "score": round(hit.score, 4)  # cosine similarity score
        })

    return formatted
