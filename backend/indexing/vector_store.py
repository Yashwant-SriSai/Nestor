# vector_store.py
# Vector search finds code by MEANING ("where is login handled?") even when the
# words differ. Chroma runs inside our own process (no separate server) and
# uses its default local embedding model, so no extra API key is needed.
# NOTE: that model (about 80 MB) downloads automatically the first time it is
# used, so the first analysis is slower and needs internet.

import chromadb

_client = None  # created on first use


def _get_client():
    global _client
    if _client is None:
        _client = chromadb.EphemeralClient()  # in memory only, nothing is saved to disk
    return _client


def build_collection(repo_id: str, chunks: list):
    # One collection per analysed repo, so repos never mix in search results.
    collection = _get_client().create_collection(name=f"repo_{repo_id}")
    for i in range(0, len(chunks), 100):  # small batches keep memory low
        batch = chunks[i:i + 100]
        collection.add(
            ids=[c["id"] for c in batch],
            # The path is part of the text, so searching for a file name can match too.
            documents=[f'{c["path"]}\n{c["text"]}' for c in batch],
        )
    return collection


def search(collection, query: str, k: int) -> list:
    count = collection.count()
    if count == 0:  # querying an empty collection raises an error
        return []
    result = collection.query(query_texts=[query], n_results=min(k, count))
    return result["ids"][0]  # chunk ids, best match first


def delete_collection(name: str) -> None:
    # Called when an old repo is dropped from memory, to free its vectors.
    try:
        _get_client().delete_collection(name)
    except Exception:  # noqa: BLE001 - already gone is fine
        pass