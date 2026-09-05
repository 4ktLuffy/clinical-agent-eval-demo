"""Sentence embeddings, pinned.

Two backends behind one function so the change can be measured rather than asserted:

  hashed  the original CRC32 bag-of-words. Deterministic, dependency-free, and not
          semantic at all -- two sentences with no shared vocabulary score ~0 however
          close their meaning.
  minilm  sentence-transformers/all-MiniLM-L6-v2, pinned to one revision. Real learned
          sentence vectors, CPU-only, no network once the weights are cached.

Selected by CLINICAL_EMBEDDINGS. The default stays `hashed` so every number already
published in this repository keeps meaning what it said; `minilm` is opt-in until its
before/after is recorded.

Determinism: the model runs in eval mode on CPU with no sampling, so the same string
always produces the same vector. tests/test_embeddings.py asserts that across two
independently constructed encoders, which is what makes a cached CI run reproducible.
"""

from __future__ import annotations

import os
from functools import lru_cache

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
# Pinned. Without a revision, a silent upstream re-upload would move every centroid and
# every retrieval score without a single line of this repository changing.
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MODEL_DIM = 384

BACKENDS = ("hashed", "minilm")


def backend() -> str:
    name = os.environ.get("CLINICAL_EMBEDDINGS", "hashed").strip().lower()
    if name not in BACKENDS:
        raise ValueError(f"CLINICAL_EMBEDDINGS must be one of {BACKENDS}, got {name!r}")
    return name


@lru_cache(maxsize=1)
def _encoder():
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device="cpu")


@lru_cache(maxsize=8192)
def encode(text: str) -> tuple[float, ...]:
    """One L2-normalised vector. Cached: the corpus and the exemplars re-encode the same
    strings many times per run, and the model is the slow part of any run that uses it."""
    vector = _encoder().encode([text], normalize_embeddings=True,
                               show_progress_bar=False)[0]
    return tuple(float(x) for x in vector)
