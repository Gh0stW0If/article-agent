from __future__ import annotations

import math
import re
from collections import Counter

from .schemas import DocumentChunk

TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text) if len(t) > 1]


class HybridRetriever:
    """Small dependency-light BM25-like retriever for the MVP.

    It keeps the API shape needed for later replacement with BM25 + embeddings.
    """

    def __init__(self, chunks: list[DocumentChunk]):
        self.chunks = chunks
        self.docs = [tokenize(f"{c.context_prefix} {c.text}") for c in chunks]
        self.df = Counter()
        for doc in self.docs:
            self.df.update(set(doc))
        self.avgdl = sum(len(d) for d in self.docs) / len(self.docs) if self.docs else 1.0

    def search(self, query: str, sections: set[str] | None = None, limit: int = 5) -> list[tuple[DocumentChunk, float]]:
        q = tokenize(query)
        scored: list[tuple[DocumentChunk, float]] = []
        for chunk, doc in zip(self.chunks, self.docs):
            if sections and chunk.section not in sections:
                continue
            tf = Counter(doc)
            score = 0.0
            for term in q:
                if term not in tf:
                    continue
                idf = math.log((len(self.docs) - self.df[term] + 0.5) / (self.df[term] + 0.5) + 1)
                denom = tf[term] + 1.5 * (1 - 0.75 + 0.75 * len(doc) / self.avgdl)
                score += idf * tf[term] * 2.5 / denom
            if score > 0:
                scored.append((chunk, score))
        return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]

