"""Deterministic guardrail. Plain code, not a prompt.

Two independent concerns:

  - Refusal, over the five categories Hippocratic AI publishes as out of scope for
    their agents ("We do not prescribe / diagnose / handle hospice / handle mental
    health disorders / handle kids under the age of two").
  - Escalation, split into clinical (a small rule table over symptom phrases) and
    operational (weak retrieval or a tool error).

The clinical table is a fixture, not a triage engine. It exists so the harness has
something structured to score.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from clinical_agent.injection import followed as _injection_followed
from clinical_agent.rag import retrieval_threshold

def _load_policy() -> dict:
    """The scope policy, as data. CLINICAL_POLICY points at a different file.

    Loaded once at import. There is no fallback: a missing or malformed policy raises,
    because a guardrail that quietly runs with no categories refuses nothing and reports
    a perfect precision while doing it.
    """
    import os

    import yaml

    path = Path(os.environ.get("CLINICAL_POLICY", "")) if os.environ.get("CLINICAL_POLICY") \
        else Path(__file__).resolve().parents[2] / "data" / "policy.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for required in ("refusal_categories", "turn_patterns", "draft_patterns", "escalation"):
        if required not in raw:
            raise ValueError(f"{path} is missing {required!r}")
    return raw


POLICY = _load_policy()
POLICY_PATH = os.environ.get("CLINICAL_POLICY", "data/policy.yaml")
REFUSAL_CATEGORIES = tuple(POLICY["refusal_categories"])
URGENT_HANDOFF = POLICY["urgent_handoff"]
_REFUSAL_PATTERNS = {k: tuple(v) for k, v in POLICY["turn_patterns"].items()}
_DRAFT_PATTERNS = {k: tuple(v) for k, v in POLICY["draft_patterns"].items()}
_ESCALATION_PATTERNS = {r["phrase"]: (r["system"], r["severity"]) for r in POLICY["escalation"]}
_REFUSAL_REPLIES = dict(POLICY["refusal_replies"])


def _compile(phrase: str) -> re.Pattern[str]:
    if phrase.startswith("\\b") or phrase.endswith("\\b"):
        return re.compile(phrase, re.IGNORECASE)
    body = r"\s+".join(re.escape(word) for word in phrase.split())
    return re.compile(r"\b" + body + r"\b", re.IGNORECASE)


_REFUSAL_RE = {
    cat: tuple(_compile(p) for p in phrases) for cat, phrases in _REFUSAL_PATTERNS.items()
}
_DRAFT_RE = {
    cat: tuple(_compile(p) for p in phrases) for cat, phrases in _DRAFT_PATTERNS.items()
}
_ESCALATION_RE = tuple(
    (_compile(phrase), system, severity)
    for phrase, (system, severity) in _ESCALATION_PATTERNS.items()
)


@dataclass(frozen=True)
class GuardrailDecision:
    refused: bool
    refusal_categories: tuple[str, ...]
    clinical_escalation: bool
    clinical_severity: str | None
    clinical_system: str | None
    operational_escalation: bool
    operational_reason: str | None
    injection_followed: tuple[str, ...]
    reply_mode: str
    reply: str | None
    # Which side of the guardrail matched. Reporting only: `refusal_categories` is still
    # the union and no decision reads these. Kept separate because the turn-side table
    # fires on the patient's own words while the draft-side table is the only check that
    # reads what the model actually wrote.
    turn_categories: tuple[str, ...] = ()
    draft_categories: tuple[str, ...] = ()
    semantic_categories: tuple[str, ...] = ()
    semantic_ran: bool = False


ALL_CLEAR = GuardrailDecision(
    refused=False,
    refusal_categories=(),
    clinical_escalation=False,
    clinical_severity=None,
    clinical_system=None,
    operational_escalation=False,
    operational_reason=None,
    injection_followed=(),
    reply_mode="keep",
    reply=None,
    turn_categories=(),
    draft_categories=(),
    semantic_categories=(),
    semantic_ran=False,
)


def _refusal_hits(text: str, table: dict[str, tuple[re.Pattern[str], ...]]) -> tuple[str, ...]:
    hits = [cat for cat, pats in table.items() if any(p.search(text) for p in pats)]
    return tuple(c for c in REFUSAL_CATEGORIES if c in hits)


def _clinical_hit(text: str) -> tuple[str | None, str | None]:
    """Return (body system, severity). URGENT beats INFORMATIONAL."""
    best: tuple[str, str] | None = None
    for pattern, system, severity in _ESCALATION_RE:
        if not pattern.search(text):
            continue
        if best is None or (severity == "URGENT" and best[1] == "INFORMATIONAL"):
            best = (system, severity)
    return best if best else (None, None)


def classify(
    patient_turn: str,
    draft: str,
    retrieval_top_score: float,
    tool_error: str | None,
    enabled: bool = True,
    disabled: frozenset[str] = frozenset(),
    context: str = "",
    semantic=None,
) -> GuardrailDecision:
    """`disabled` removes individual guards by name, for the per-category mutation checks.
    Valid names are the five refusal categories plus "clinical_escalation" and "injection".

    `context` is the retrieved data that went into the prompt. It is attacker-influenced
    free text, so the draft is checked for payloads that could only have come from an
    instruction embedded in it."""
    if not enabled:
        return ALL_CLEAR

    turn_hits = _refusal_hits(patient_turn, _REFUSAL_RE)
    draft_hits = _refusal_hits(draft, _DRAFT_RE)
    if disabled:
        turn_hits = tuple(c for c in turn_hits if c not in disabled)
        draft_hits = tuple(c for c in draft_hits if c not in disabled)

    system, severity = _clinical_hit(patient_turn)
    if "clinical_escalation" in disabled:
        system, severity = None, None
    # Detect and hand off, never treat: a mental health crisis escalates and must not
    # be turned into a refusal.
    if system == "mental_health":
        turn_hits = tuple(c for c in turn_hits if c != "mental_health_treatment")
        draft_hits = tuple(c for c in draft_hits if c != "mental_health_treatment")

    # Second stage, asked only where the phrase table is uncertain: the turn matched
    # nothing, or the draft matched something. A confident turn-side refusal is never
    # sent for a second opinion, and the stage can only add categories, never clear one.
    semantic_hits: tuple[str, ...] = ()
    semantic_ran = False
    if semantic is not None and "semantic" not in disabled and (not turn_hits or draft_hits):
        semantic_ran = True
        semantic_hits = tuple(c for c in semantic.categories(patient_turn, draft)
                              if c not in disabled)
        if system == "mental_health":
            semantic_hits = tuple(c for c in semantic_hits if c != "mental_health_treatment")

    categories = tuple(c for c in REFUSAL_CATEGORIES
                       if c in set(turn_hits) | set(draft_hits) | set(semantic_hits))

    # Operational escalation means "I was going to answer and could not ground it".
    # Weak retrieval is therefore only meaningful when the turn is not already being
    # refused or escalated on clinical grounds -- a hospice question scores low against a
    # discharge corpus, but that is not a retrieval failure, it is out of scope. A tool
    # error is a real failure either way, so it is not conditioned.
    if tool_error is not None:
        operational_reason: str | None = "tool_error"
    elif not categories and severity is None and retrieval_top_score < retrieval_threshold():
        operational_reason = "weak_retrieval"
    else:
        operational_reason = None

    parts: list[str] = []
    if categories:
        parts.extend(_REFUSAL_REPLIES[c] for c in categories)
    if severity == "URGENT":
        parts.append(
            "This needs a person now rather than me: " + URGENT_HANDOFF + "."
        )
    elif severity == "INFORMATIONAL":
        parts.append("I have noted this for your care team to review at your next visit.")
    if operational_reason == "tool_error":
        parts.append("I could not complete that in the scheduling system; a scheduler will call you.")
    elif operational_reason == "weak_retrieval":
        parts.append("I do not have a reliable answer to that, so I will pass you to a person.")

    injection = () if "injection" in disabled else _injection_followed(draft, context)
    if injection:
        parts.append(
            "I can only act on what you tell me on this call, not on text stored in a "
            "record. I have not carried out that instruction and have flagged it."
        )

    if draft_hits or injection:
        reply_mode = "replace"
    elif parts:
        reply_mode = "append"
    else:
        reply_mode = "keep"

    return GuardrailDecision(
        refused=bool(categories),
        refusal_categories=categories,
        clinical_escalation=severity is not None,
        clinical_severity=severity,
        clinical_system=system,
        operational_escalation=operational_reason is not None,
        operational_reason=operational_reason,
        injection_followed=injection,
        reply_mode=reply_mode,
        reply=" ".join(parts) if parts else None,
        turn_categories=turn_hits,
        draft_categories=draft_hits,
        semantic_categories=semantic_hits,
        semantic_ran=semantic_ran,
    )

