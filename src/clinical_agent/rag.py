"""Deterministic retrieval over the synthetic corpus.

Embeddings are hashed bag-of-words rather than a learned model: no download, no
network, and byte-identical vectors on every machine and in CI. zlib.crc32 is used
for bucketing because the builtin hash() is salted per process and would make runs
irreproducible.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from math import sqrt
from pathlib import Path

DIM = 512
# Per backend: the hashed space and the MiniLM space put unrelated text at very different
# cosine values, so one number cannot serve both. Each is derived by the same rule, in
# scripts/retrieval_threshold.py, and neither is fitted to any held-out set.
_RETRIEVAL_THRESHOLDS = {"hashed": 0.18, "minilm": 0.405627}


def retrieval_threshold() -> float:
    from clinical_agent.embeddings import backend

    return _RETRIEVAL_THRESHOLDS[backend()]


RETRIEVAL_THRESHOLD = 0.18

_STOPWORDS = frozenset(
    """a an and are as at be but by can do does for from had has have how i if in is it its
    my of on or our should that the their them then there these they this to was we were
    what when where which who will with you your""".split()
)

_TOKEN = re.compile(r"[a-z0-9]+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

CHUNK_SENTENCES = 3
CHUNK_OVERLAP = 1


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc: str
    text: str


@dataclass(frozen=True)
class Retrieved:
    chunk: Chunk
    score: float


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


def _embed_hashed(text: str) -> list[float]:
    """Hashed bag of words, L2-normalised. Cosine similarity is then a dot product."""
    vec = [0.0] * DIM
    for token in _tokens(text):
        vec[zlib.crc32(token.encode("utf-8")) % DIM] += 1.0
    norm = sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


def embed(text: str) -> list[float]:
    """Whichever backend CLINICAL_EMBEDDINGS names. Both are L2-normalised, so cosine is
    a dot product either way and every caller is unchanged.

    The two spaces are not comparable: a threshold calibrated on one is meaningless on the
    other, which is why RETRIEVAL_THRESHOLD and the semantic stage's threshold are both
    resolved per backend rather than being single constants."""
    from clinical_agent.embeddings import backend, encode

    if backend() == "minilm":
        return list(encode(text))
    return _embed_hashed(text)


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _chunk_document(doc: str, text: str) -> list[Chunk]:
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    sentences = [s.strip() for s in _SENTENCE.split(body) if s.strip()]
    chunks: list[Chunk] = []
    step = max(1, CHUNK_SENTENCES - CHUNK_OVERLAP)
    for index, start in enumerate(range(0, max(1, len(sentences)), step)):
        window = sentences[start : start + CHUNK_SENTENCES]
        if not window:
            break
        chunks.append(Chunk(chunk_id=f"{doc}#{index}", doc=doc, text=" ".join(window)))
        if start + CHUNK_SENTENCES >= len(sentences):
            break
    return chunks


class Corpus:
    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks
        self._vectors = [embed(c.text) for c in chunks]

    @classmethod
    def load(cls, corpus_dir: Path) -> "Corpus":
        chunks: list[Chunk] = []
        for path in sorted(Path(corpus_dir).glob("*.md")):
            chunks.extend(_chunk_document(path.name, path.read_text(encoding="utf-8")))
        return cls(chunks)

    def __len__(self) -> int:
        return len(self._chunks)

    def retrieve(self, query: str, k: int = 3) -> list[Retrieved]:
        q = embed(query)
        scored = [
            Retrieved(chunk=chunk, score=_cosine(q, vec))
            for chunk, vec in zip(self._chunks, self._vectors)
        ]
        scored.sort(key=lambda r: (-r.score, r.chunk.chunk_id))
        return scored[:k]
