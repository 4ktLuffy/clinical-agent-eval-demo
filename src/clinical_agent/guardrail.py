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

import re
from dataclasses import dataclass

from clinical_agent.injection import followed as _injection_followed
from clinical_agent.rag import RETRIEVAL_THRESHOLD

REFUSAL_CATEGORIES = (
    "prescribe",
    "diagnose",
    "hospice",
    "mental_health_treatment",
    "under_two",
)

URGENT_HANDOFF = "escalate to on-call clinician; crisis line per deployment config"

# No crisis telephone number appears anywhere in this repository. A demo is the wrong
# place to ship a number that could be wrong, stale, or wrong for the caller's country.

_REFUSAL_PATTERNS: dict[str, tuple[str, ...]] = {
    "prescribe": (
        "should i take", "should i be taking", "what dose", "what dosage",
        "double my dose", "double up on", "stop taking my", "start taking",
        "prescribe me", "can you prescribe", "switch me to", "increase my dose",
        "lower my dose", "skip a dose", "up my dose",
    ),
    "diagnose": (
        # "do i have" must not swallow "do I have TO" -- a different construction that
        # asks about an obligation, not a condition ("do I have to book parking?").
        r"\bdo\s+i\s+have\b(?!\s+to\b)", "do you think i have", "diagnose me",
        "what's wrong with me",
        "what is wrong with me", "am i having a", "is it cancer", "is this cancer",
        "does this mean i have", "what condition do i have",
    ),
    "hospice": (
        "hospice", "end of life", "end-of-life", "comfort care only", "palliative care",
    ),
    "mental_health_treatment": (
        "treat my depression", "treat my anxiety", "manage my depression",
        "manage my anxiety", "therapy for my", "counsel me",
        "start me on an antidepressant", "psychiatric medication", "be my therapist",
    ),
    "under_two": (
        r"\bnewborn\b", r"\binfant\b", "my baby",
        r"\b\d{1,2}[- ]month[- ]old\b", r"\b\d{1,2}[- ]week[- ]old\b",
    ),
}

# phrase -> (body system, severity)
_ESCALATION_PATTERNS: dict[str, tuple[str, str]] = {
    "chest pain": ("cardiovascular_respiratory", "URGENT"),
    "can't catch my breath": ("cardiovascular_respiratory", "URGENT"),
    "cannot catch my breath": ("cardiovascular_respiratory", "URGENT"),
    "short of breath": ("cardiovascular_respiratory", "URGENT"),
    "shortness of breath": ("cardiovascular_respiratory", "URGENT"),
    "wheezing": ("cardiovascular_respiratory", "URGENT"),
    "worst headache": ("neurological", "URGENT"),
    "slurred": ("neurological", "URGENT"),
    "face is drooping": ("neurological", "URGENT"),
    "numb on one side": ("neurological", "URGENT"),
    "vision went": ("neurological", "URGENT"),
    "seizure": ("neurological", "URGENT"),
    "vomiting blood": ("gastrointestinal", "URGENT"),
    "blood in my stool": ("gastrointestinal", "URGENT"),
    "black stool": ("gastrointestinal", "URGENT"),
    "constipated for": ("gastrointestinal", "INFORMATIONAL"),
    "not been able to urinate": ("genitourinary", "URGENT"),
    "haven't been able to urinate": ("genitourinary", "URGENT"),
    "blood in my urine": ("genitourinary", "URGENT"),
    "red and swollen": ("wound_skin", "URGENT"),
    "pus": ("wound_skin", "URGENT"),
    "red streaks": ("wound_skin", "URGENT"),
    "itchy rash": ("wound_skin", "INFORMATIONAL"),
    "can't put weight on": ("musculoskeletal", "URGENT"),
    "heard a pop": ("musculoskeletal", "URGENT"),
    "knee has been bothering": ("musculoskeletal", "INFORMATIONAL"),
    "sore after": ("musculoskeletal", "INFORMATIONAL"),
    "don't want to be here anymore": ("mental_health", "URGENT"),
    "want to end it": ("mental_health", "URGENT"),
    "hurt myself": ("mental_health", "URGENT"),
    "no reason to go on": ("mental_health", "URGENT"),
}

# Patient-voiced phrases do not fire on an assistant-voiced draft ("do i have" is not
# something a draft says). These are the draft-side equivalents, checked only against the
# model output. Without them the draft could assert a diagnosis and pass.
_DRAFT_PATTERNS: dict[str, tuple[str, ...]] = {
    "prescribe": (
        "you should take", "take an extra", "you can double", "fine to skip",
        "start taking", "what dose", "double up on",
    ),
    "diagnose": (
        "sounds like you have", "looks like you have", "you likely have",
        "you are having a", "you probably have", "this is almost certainly",
    ),
    "hospice": ("hospice", "end of life", "end-of-life", "palliative care"),
    "mental_health_treatment": (
        "breathing exercise", "cognitive behavioural", "cognitive behavioral",
        "psychiatric medication", "thought record",
    ),
    "under_two": (r"\bnewborn\b", r"\binfant\b"),
}

_REFUSAL_REPLIES: dict[str, str] = {
    "prescribe": (
        "I am not able to advise on starting, stopping or changing a medication or a "
        "dose. I can note this for your care team and have someone call you back."
    ),
    "diagnose": (
        "I am not able to tell you what condition you have. I can pass what you have "
        "described to your care team and have a person follow up with you."
    ),
    "hospice": (
        "Hospice and end-of-life planning is handled by your care team rather than by "
        "me. I can arrange for someone to call you about it."
    ),
    "mental_health_treatment": (
        "I am not able to provide treatment for a mental health condition. I can "
        "connect you with a person on your care team."
    ),
    "under_two": (
        "I am not able to help with care for a child under two years old. Please speak "
        "to your paediatric care team, and I can arrange a call back."
    ),
}


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
    elif not categories and severity is None and retrieval_top_score < RETRIEVAL_THRESHOLD:
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

