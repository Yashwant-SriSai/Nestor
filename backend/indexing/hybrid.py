# hybrid.py
# Meaning search (Chroma) and keyword search (BM25) each miss things the other
# finds. We run both and merge the two rankings with "reciprocal rank fusion":
# a chunk ranked high in EITHER list floats up, and one ranked high in BOTH wins.

from backend.indexing import vector_store
from backend.indexing.bm25_store import BM25Index

RRF_K = 60  # standard constant; it softens the gap between rank 1 and rank 2


def _fuse(rankings: list) -> list:
    scores = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (RRF_K + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)


class RepoIndex:
    """Everything needed to search ONE repo: its chunks, BM25 index and Chroma collection."""

    def __init__(self, repo_id: str, chunks: list):
        self.by_id = {c["id"]: c for c in chunks}
        self.bm25 = BM25Index(chunks)
        self.collection = vector_store.build_collection(repo_id, chunks)

    def search(self, query: str, k: int) -> list:
        wide = k * 2  # ask each engine for extra results, so the merge has choices
        fused = _fuse([vector_store.search(self.collection, query, wide),
                       self.bm25.search(query, wide)])
        return [self.by_id[i] for i in fused[:k] if i in self.by_id]

    def close(self) -> None:
        vector_store.delete_collection(self.collection.name)