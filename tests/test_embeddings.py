"""The embedding backend must be pinned, deterministic, and opt-in."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clinical_agent import embeddings  # noqa: E402

# No module-level skip: minilm is the default backend, so these must run in CI. A skip
# here would also trip the zero-skip gate, which is the point of that gate.
pytestmark = pytest.mark.skipif(
    embeddings.backend() != "minilm",
    reason="only meaningful for the minilm backend",
)


def test_model_and_revision_are_pinned():
    """An unpinned revision lets a silent upstream re-upload move every centroid and every
    retrieval score without one line of this repository changing."""
    assert embeddings.MODEL_NAME == "sentence-transformers/all-MiniLM-L6-v2"
    assert len(embeddings.MODEL_REVISION) == 40, "revision must be a full commit sha"
    assert embeddings.MODEL_DIM == 384


def test_two_independent_encoders_agree_exactly():
    """Determinism is what makes a cached CI run reproducible. Clearing the cached encoder
    forces a genuine second construction rather than re-reading one object."""
    text = "Dad is on the end-stage pathway now and we want to plan."
    embeddings.encode.cache_clear()
    embeddings._encoder.cache_clear()
    first = embeddings.encode(text)
    embeddings.encode.cache_clear()
    embeddings._encoder.cache_clear()
    second = embeddings.encode(text)
    assert first == second
    assert len(first) == embeddings.MODEL_DIM


def test_vectors_are_normalised():
    vector = embeddings.encode("a routine appointment question")
    assert abs(sum(x * x for x in vector) ** 0.5 - 1.0) < 1e-5


def test_backend_rejects_an_unknown_name(monkeypatch):
    monkeypatch.setenv("CLINICAL_EMBEDDINGS", "word2vec")
    with pytest.raises(ValueError, match="CLINICAL_EMBEDDINGS"):
        embeddings.backend()
