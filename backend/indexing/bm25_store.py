# bm25_store.py
# Keyword search catches EXACT names (normalisation.py, get_user) that
# meaning-based vector search can miss. BM25 is the classic ranking formula
# used by simple search engines.

import re

from rank_bm25 import BM25Okapi


def tokenize(text: str) -> list:
    # Split camelCase and snake_case so "getUserName" and "get_user_name" both
    # become ["get", "user", "name"], and "normalisation.py" becomes
    # ["normalisation", "py"]. Queries use the same rules, so they match.
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return re.findall(r"[a-z]+|\d+", text.lower())


class BM25Index:
    def __init__(self, chunks: list):
        self.ids = [c["id"] for c in chunks]
        # The path is searchable too, like in the vector store.
        corpus = [tokenize(f'{c["path"]} {c["text"]}') for c in chunks]
        self.bm25 = BM25Okapi(corpus) if corpus else None  # BM25 crashes on an empty corpus

    def search(self, query: str, k: int) -> list:
        tokens = tokenize(query)
        if self.bm25 is None or not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        # Score 0 means "no query word appears in this chunk", so we drop it.
        return [self.ids[i] for i in ranked[:k] if scores[i] > 0]