"""A quota that ran out and a model that cannot answer are opposite conclusions.

The first version of this gate counted them together and printed "STAGE UNUSABLE: 433/564
failed", which reads as a verdict on the model. The model was fine; the day's free tokens
were gone.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clinical_agent.semantic import LLMSemanticStage  # noqa: E402


class _Boom:
    def __init__(self, exc):
        self.exc = exc

    class _Chat:
        def __init__(self, exc):
            self.completions = _Boom._Completions(exc)

    class _Completions:
        def __init__(self, exc):
            self.exc = exc

        def create(self, **_):
            raise self.exc

    @property
    def chat(self):
        return _Boom._Chat(self.exc)


def _stage_that_raises(exc) -> LLMSemanticStage:
    stage = LLMSemanticStage("test-model", base_url="http://x", api_key="k")
    stage._client = _Boom(exc)
    return stage


def test_a_rate_limit_is_counted_as_a_rate_limit():
    import openai

    error = openai.RateLimitError(
        "Rate limit reached ... tokens per day (TPD)",
        response=type("R", (), {"status_code": 429, "headers": {}, "request": None})(),
        body=None)
    stage = _stage_that_raises(error)
    assert stage.categories("anything", "") == ()
    assert stage.rate_limited == 1
    assert stage.unparseable == 0


def test_any_other_failure_is_counted_separately():
    stage = _stage_that_raises(ValueError("garbage from the model"))
    assert stage.categories("anything", "") == ()
    assert stage.unparseable == 1
    assert stage.rate_limited == 0


def test_a_failure_is_never_cached():
    """A transient failure must not freeze an empty verdict in for the rest of the run,
    and must not be written to the resume cache as though it were an answer."""
    stage = _stage_that_raises(ValueError("boom"))
    stage.categories("a turn", "")
    stage.categories("a turn", "")
    assert stage.failures == 2, "the second call reused a cached failure"
    assert "a turn" not in stage._cache


def test_the_gate_separates_the_two_outcomes():
    source = (ROOT / "scripts" / "heldout_recall.py").read_text(encoding="utf-8")
    assert "INCOMPLETE" in source and "return 4" in source
    assert "STAGE UNUSABLE" in source and "return 3" in source
    assert "unparseable > 0.2 * attempts" in source
