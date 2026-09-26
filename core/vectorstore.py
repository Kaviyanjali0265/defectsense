import os

import chromadb
import ollama

CHROMA_PATH = os.getenv("CHROMA_PATH", ".data/chroma")
EMBED_MODEL = "nomic-embed-text"

# Collection the live pipeline reads/writes verified history from. Overridable so
# eval scripts can point the exact same search()/fetch_seen_before() machinery at a
# separate eval-only collection without ever touching live data. Default unchanged.
DEFECT_HISTORY_COLLECTION = os.getenv("DEFECT_HISTORY_COLLECTION", "defect_history")

_client = None


def get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
    return _client


def _embed(text: str) -> list[float]:
    response = ollama.embeddings(model=EMBED_MODEL, prompt=text)
    return response["embedding"]


def upsert(collection_name: str, doc_id: str, text: str, metadata: dict, collection_metadata: dict | None = None):
    """collection_metadata (e.g. {"hnsw:space": "cosine"}) only takes effect the first
    time a collection is created — ignored on subsequent calls once it already exists."""
    kwargs = {"name": collection_name}
    if collection_metadata:
        kwargs["metadata"] = collection_metadata
    col = get_client().get_or_create_collection(**kwargs)
    col.upsert(
        ids=[doc_id],
        embeddings=[_embed(text)],
        documents=[text],
        metadatas=[metadata],
    )


def search(collection_name: str, query: str, n_results: int = 3, where: dict | None = None) -> list[dict]:
    col = get_client().get_or_create_collection(collection_name)
    kwargs = {"query_embeddings": [_embed(query)], "n_results": n_results}
    if where:
        kwargs["where"] = where
    results = col.query(**kwargs)
    if not results["documents"][0]:
        return []
    return [
        {"text": doc, "metadata": meta, "distance": dist}
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )
    ]


def get_all(collection_name: str, where: dict | None = None) -> list[dict]:
    """Fetch every doc's metadata matching `where`, with no embedding/ranking involved —
    for building a random-retrieval baseline pool. Not used by any production code path."""
    col = get_client().get_or_create_collection(collection_name)
    kwargs = {}
    if where:
        kwargs["where"] = where
    results = col.get(**kwargs)
    return [
        {"text": doc, "metadata": meta}
        for doc, meta in zip(results["documents"], results["metadatas"])
    ]


def fetch_seen_before(step: str, mechanism: str, n_results: int = 3) -> list[dict]:
    """Past verified cases of this exact mechanism at this step, from DEFECT_HISTORY_COLLECTION.
    Shared by the pipeline (at report-generation time) and the verify API (at verify time)."""
    try:
        query = f"{step} {mechanism} verified"
        results = search(DEFECT_HISTORY_COLLECTION, query, n_results=n_results, where={"step": step})
        return [r["metadata"] for r in results if r["metadata"].get("mechanism") == mechanism]
    except Exception:  # noqa: BLE001 — best-effort lookup, any failure returns empty
        return []
