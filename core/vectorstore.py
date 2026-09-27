import uuid

import ollama
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from core.settings import settings

QDRANT_URL  = settings.qdrant_url
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM   = 768  # nomic-embed-text's fixed output size — Qdrant needs this upfront
                    # at collection-creation time, unlike Chroma which infers it.

# Collection the live pipeline reads/writes verified history from. Overridable so
# eval scripts can point the exact same search()/fetch_seen_before() machinery at a
# separate eval-only collection without ever touching live data. Default unchanged.
DEFECT_HISTORY_COLLECTION = settings.defect_history_collection

_client = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=QDRANT_URL)
    return _client


def _embed(text: str) -> list[float]:
    response = ollama.embeddings(model=EMBED_MODEL, prompt=text)
    return response["embedding"]


def _point_id(doc_id: str) -> str:
    """Qdrant point IDs must be an unsigned int or a UUID, not an arbitrary string —
    deterministic UUID5 from doc_id so the same doc_id always maps to the same point
    (upsert stays idempotent, same as it was with Chroma's plain string IDs). The
    original string doc_id is kept in the payload so it's still visible on read."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id))


def _distance_for(collection_metadata: dict | None) -> Distance:
    # Same {"hnsw:space": "cosine"|"l2"} convention evals/build_history.py already
    # uses for Chroma, so that file needs zero changes for this swap.
    space = (collection_metadata or {}).get("hnsw:space", "l2")
    return Distance.COSINE if space == "cosine" else Distance.EUCLID


def _ensure_collection(collection_name: str, collection_metadata: dict | None = None) -> None:
    """Chroma's get_or_create_collection had no separate "does it exist" step; Qdrant
    needs one explicit check before any operation, read or write, since querying a
    missing collection is an error rather than an empty result."""
    client = get_client()
    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=EMBED_DIM, distance=_distance_for(collection_metadata)),
        )


def _filter_for(where: dict | None) -> Filter | None:
    if not where:
        return None
    return Filter(must=[FieldCondition(key=f"metadata.{k}", match=MatchValue(value=v)) for k, v in where.items()])


def upsert(collection_name: str, doc_id: str, text: str, metadata: dict, collection_metadata: dict | None = None):
    """collection_metadata (e.g. {"hnsw:space": "cosine"}) only takes effect the first
    time a collection is created — ignored on subsequent calls once it already exists."""
    _ensure_collection(collection_name, collection_metadata)
    get_client().upsert(
        collection_name=collection_name,
        points=[
            PointStruct(
                id=_point_id(doc_id),
                vector=_embed(text),
                payload={"doc_id": doc_id, "text": text, "metadata": metadata},
            )
        ],
    )


def search(collection_name: str, query: str, n_results: int = 3, where: dict | None = None) -> list[dict]:
    _ensure_collection(collection_name)
    result = get_client().query_points(
        collection_name=collection_name,
        query=_embed(query),
        query_filter=_filter_for(where),
        limit=n_results,
    )
    # "distance" here is Qdrant's similarity SCORE (higher = more similar for both
    # cosine and Euclid distance types), the opposite sense of Chroma's "distance"
    # (lower = more similar) — harmless since no caller reads this field, but worth
    # knowing if that ever changes.
    return [
        {"text": p.payload["text"], "metadata": p.payload["metadata"], "distance": p.score}
        for p in result.points
    ]


def get_all(collection_name: str, where: dict | None = None) -> list[dict]:
    """Fetch every doc's metadata matching `where`, with no embedding/ranking involved —
    for building a random-retrieval baseline pool. Not used by any production code path."""
    _ensure_collection(collection_name)
    points, _ = get_client().scroll(
        collection_name=collection_name,
        scroll_filter=_filter_for(where),
        limit=10_000,
    )
    return [{"text": p.payload["text"], "metadata": p.payload["metadata"]} for p in points]


def fetch_seen_before(step: str, mechanism: str, n_results: int = 3) -> list[dict]:
    """Past verified cases of this exact mechanism at this step, from DEFECT_HISTORY_COLLECTION.
    Shared by the pipeline (at report-generation time) and the verify API (at verify time)."""
    try:
        query = f"{step} {mechanism} verified"
        results = search(DEFECT_HISTORY_COLLECTION, query, n_results=n_results, where={"step": step})
        return [r["metadata"] for r in results if r["metadata"].get("mechanism") == mechanism]
    except Exception:  # noqa: BLE001 — best-effort lookup, any failure returns empty
        return []
