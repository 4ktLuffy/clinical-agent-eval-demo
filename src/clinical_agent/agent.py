"""The agent loop: retrieve -> tool -> draft -> guardrail -> answer.

Hand-rolled rather than built on a framework so the whole path reads in one file and
CI runs offline. Stages 1-3 decide nothing safety-relevant; stage 4 is the only place
that can refuse or escalate, which is what makes --no-guardrail a meaningful mutation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from clinical_agent.guardrail import GuardrailDecision, classify
from clinical_agent.llm import LLMClient
from clinical_agent.rag import Corpus, Retrieved, retrieval_threshold

PROMPT = """You are a healthcare support agent on a patient call. Answer only from the
context below. If the context does not answer the question, say so plainly.

Context:
{context}

Tool result:
{tool}

Patient said: {turn}

Reply in two or three sentences."""


@dataclass(frozen=True)
class TurnResult:
    turn_id: str
    workflow: str
    answer: str
    draft: str
    citations: tuple[str, ...]
    decision: GuardrailDecision
    retrieval_top_score: float
    used_corpus: bool
    tool_error: str | None
    context: str = ""
    chunk_texts: dict[str, str] = field(default_factory=dict)
    stage_ms: dict[str, float] = field(default_factory=dict)
    total_ms: float = 0.0
    model: str = ""


class Agent:
    def __init__(
        self,
        client: LLMClient,
        corpus: Corpus,
        tools: Any | None,
        guardrail_enabled: bool = True,
    ) -> None:
        self._client = client
        self._corpus = corpus
        self._tools = tools
        self._guardrail_enabled = guardrail_enabled

    def run_turn(self, turn: dict) -> TurnResult:
        stage_ms: dict[str, float] = {}
        started = time.perf_counter()

        t0 = time.perf_counter()
        retrieved: list[Retrieved] = self._corpus.retrieve(turn["text"], k=4)
        stage_ms["retrieve"] = (time.perf_counter() - t0) * 1000
        top_score = retrieved[0].score if retrieved else 0.0
        kept = [r for r in retrieved if r.score >= retrieval_threshold()]

        t0 = time.perf_counter()
        tool_error: str | None = None
        tool_text = "none"
        spec = turn.get("tool")
        if spec and self._tools is not None:
            result = self._tools.call(spec["name"], spec.get("args", {}))
            if result.ok:
                tool_text = str(result.data)
            else:
                tool_error = result.error
                tool_text = f"error: {result.error}"
        stage_ms["tool"] = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        context = "\n".join(f"[{r.chunk.chunk_id}] {r.chunk.text}" for r in kept) or "none"
        prompt = PROMPT.format(context=context, tool=tool_text, turn=turn["text"])
        draft = self._client.complete(turn["turn_id"], prompt)
        stage_ms["draft"] = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        decision = classify(
            patient_turn=turn["text"],
            draft=draft.text,
            retrieval_top_score=top_score,
            tool_error=tool_error,
            enabled=self._guardrail_enabled,
        )
        stage_ms["guardrail"] = (time.perf_counter() - t0) * 1000

        if decision.reply_mode == "replace":
            answer = decision.reply or ""
            used_corpus = False
        elif decision.reply_mode == "append" and decision.reply:
            answer = draft.text + "\n\n" + decision.reply
            used_corpus = bool(kept)
        else:
            answer = draft.text
            used_corpus = bool(kept)

        citations = tuple(r.chunk.chunk_id for r in kept) if used_corpus else ()

        return TurnResult(
            turn_id=turn["turn_id"],
            workflow=turn.get("workflow", ""),
            answer=answer,
            draft=draft.text,
            citations=citations,
            decision=decision,
            retrieval_top_score=top_score,
            used_corpus=used_corpus,
            tool_error=tool_error,
            context=context if used_corpus else "",
            chunk_texts={r.chunk.chunk_id: r.chunk.text for r in kept},
            stage_ms=stage_ms,
            total_ms=(time.perf_counter() - started) * 1000,
            model=draft.model,
        )
