"""Removing the guardrail must make the safety numbers worse."""

import json
from pathlib import Path

from clinical_agent.agent import Agent
from clinical_agent.guardrail import classify
from clinical_agent.llm import MockClient
from clinical_agent.rag import Corpus
from eval.stats import scored

ROOT = Path(__file__).resolve().parents[1]


def _recalls(guardrail: bool) -> tuple[float, float]:
    turns = json.loads((ROOT / "data" / "turns.json").read_text(encoding="utf-8"))
    corpus = Corpus.load(ROOT / "data" / "corpus")
    client = MockClient({t["turn_id"]: t["mock_draft"] for t in turns})
    agent = Agent(client, corpus, None, guardrail_enabled=guardrail)
    results = [agent.run_turn(t) for t in turns]
    refusal = scored(
        [r.decision.refused for r in results],
        [t["labels"]["should_refuse"] for t in turns],
    )
    clinical = scored(
        [r.decision.clinical_escalation for r in results],
        [t["labels"]["clinical_escalation"] for t in turns],
    )
    return refusal["recall"], clinical["recall"]


def test_both_recalls_drop_without_the_guardrail():
    on_refusal, on_clinical = _recalls(True)
    off_refusal, off_clinical = _recalls(False)
    assert off_refusal < on_refusal, "refusal recall did not drop"
    assert off_clinical < on_clinical, "clinical escalation recall did not drop"


def test_guardrail_on_actually_catches_something():
    on_refusal, on_clinical = _recalls(True)
    assert on_refusal > 0.0 and on_clinical > 0.0
