import chromadb
import ollama
import os

CHROMA_PATH = os.getenv("CHROMA_PATH", ".data/chroma")
EMBED_MODEL = "nomic-embed-text"

_client = None


def get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
    return _client


def _embed(text: str) -> list[float]:
    response = ollama.embeddings(model=EMBED_MODEL, prompt=text)
    return response["embedding"]


def upsert(collection_name: str, doc_id: str, text: str, metadata: dict):
    col = get_client().get_or_create_collection(collection_name)
    col.upsert(
        ids=[doc_id],
        embeddings=[_embed(text)],
        documents=[text],
        metadatas=[metadata],
    )


def search(collection_name: str, query: str, n_results: int = 3) -> list[dict]:
    col = get_client().get_or_create_collection(collection_name)
    results = col.query(
        query_embeddings=[_embed(query)],
        n_results=n_results,
    )
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
