from pathlib import Path

from clinical_agent.agent import Agent
from clinical_agent.llm import MockClient
from clinical_agent.rag import RETRIEVAL_THRESHOLD, Corpus

ROOT = Path(__file__).resolve().parents[1]


def test_retrieval_is_deterministic():
    a = Corpus.load(ROOT / "data" / "corpus").retrieve("what are the visiting hours", k=3)
    b = Corpus.load(ROOT / "data" / "corpus").retrieve("what are the visiting hours", k=3)
    assert [(r.chunk.chunk_id, r.score) for r in a] == [(r.chunk.chunk_id, r.score) for r in b]


def test_on_corpus_scores_above_threshold(corpus):
    top = corpus.retrieve("What are the visiting hours on the general wards?", k=1)[0]
    assert top.score >= RETRIEVAL_THRESHOLD


def test_off_corpus_scores_below_threshold(corpus):
    top = corpus.retrieve("What is the wifi password for visitors?", k=1)[0]
    assert top.score < RETRIEVAL_THRESHOLD


def test_grounded_answer_carries_citations(corpus, turns):
    turn = next(t for t in turns if t["turn_id"] == "T039")
    agent = Agent(MockClient({turn["turn_id"]: turn["mock_draft"]}), corpus, None)
    result = agent.run_turn(turn)
    assert result.used_corpus
    assert result.citations
    assert all("#" in c for c in result.citations)


def test_citations_empty_when_corpus_unused(corpus, turns):
    turn = next(t for t in turns if t["turn_id"] == "T035")
    agent = Agent(MockClient({turn["turn_id"]: turn["mock_draft"]}), corpus, None)
    result = agent.run_turn(turn)
    assert not result.used_corpus
    assert result.citations == ()
