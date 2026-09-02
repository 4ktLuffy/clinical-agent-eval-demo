"""The fixtures are synthetic and the labels were written by us. This checks both."""

import json
import re
from collections import Counter
from pathlib import Path

from clinical_agent.guardrail import REFUSAL_CATEGORIES

ROOT = Path(__file__).resolve().parents[1]
MRN = re.compile(r"^TEST-\d{4}$")
OBLIQUE_BY_DESIGN = {"T005"}
EXPECTED_MISMATCHES = {"T005", "T049", "T050"}


def test_fifty_turns_with_unique_ids(turns):
    assert len(turns) == 50
    assert len({t["turn_id"] for t in turns}) == 50


def test_composition(turns):
    refusals = [t for t in turns if t["labels"]["should_refuse"]]
    assert len(refusals) == 25
    per_category = Counter(c for t in refusals for c in t["labels"]["refusal_categories"])
    assert dict(per_category) == {c: 5 for c in REFUSAL_CATEGORIES}
    assert sum(1 for t in turns if t["labels"]["clinical_escalation"]) == 8
    assert sum(1 for t in turns if t["labels"]["operational_escalation"]) == 5
    safe = [
        t
        for t in turns
        if not (
            t["labels"]["should_refuse"]
            or t["labels"]["clinical_escalation"]
            or t["labels"]["operational_escalation"]
        )
    ]
    assert len(safe) == 12


def test_escalation_severities(turns):
    escalations = [t for t in turns if t["labels"]["clinical_escalation"]]
    severities = Counter(t["labels"]["clinical_severity"] for t in escalations)
    assert severities["INFORMATIONAL"] >= 2
    assert severities["URGENT"] >= 1


def test_mental_health_crisis_turn_is_not_a_refusal(turns):
    crisis = [t for t in turns if "don't want to be here anymore" in t["text"]]
    assert len(crisis) == 1
    assert crisis[0]["labels"]["clinical_escalation"]
    assert crisis[0]["labels"]["clinical_severity"] == "URGENT"
    assert not crisis[0]["labels"]["should_refuse"]


def test_operational_reasons(turns):
    reasons = Counter(
        t["labels"]["operational_reason"] for t in turns if t["labels"]["operational_escalation"]
    )
    assert reasons == {"weak_retrieval": 3, "tool_error": 2}


def test_every_mrn_is_synthetic(turns):
    for t in turns:
        if t["patient_mrn"] is not None:
            assert MRN.match(t["patient_mrn"]), t["turn_id"]
    patients = json.loads((ROOT / "data" / "patients.json").read_text(encoding="utf-8"))
    for patient in patients["patients"]:
        for identifier in patient["identifier"]:
            assert MRN.match(identifier["value"])
        assert patient["birthDate"].endswith("-01-01")


def test_safe_turns_carry_no_positive_labels(turns):
    for t in turns:
        labels = t["labels"]
        if labels["should_refuse"] or labels["clinical_escalation"] or labels["operational_escalation"]:
            continue
        assert labels["refusal_categories"] == []
        assert labels["clinical_severity"] is None
        assert labels["operational_reason"] is None


def test_documented_imperfections_are_documented(turns):
    by_id = {t["turn_id"]: t for t in turns}
    for turn_id in EXPECTED_MISMATCHES:
        note = by_id[turn_id]["note"].upper()
        assert "DELIBERATE" in note, turn_id


def test_every_refusal_positive_has_a_trigger_except_the_oblique_one(turns):
    from clinical_agent.guardrail import _REFUSAL_RE

    for t in turns:
        if not t["labels"]["should_refuse"]:
            continue
        hit = any(
            p.search(t["text"])
            for category in t["labels"]["refusal_categories"]
            for p in _REFUSAL_RE[category]
        )
        if t["turn_id"] in OBLIQUE_BY_DESIGN:
            assert not hit, "the oblique turn is supposed to miss the table"
        else:
            assert hit, t["turn_id"]


def test_open_ended_turns_carry_graded_judge_labels(turns):
    """The 11 open-ended turns are hand-labelled 0 / 0.5 / 1; the rest carry no label."""
    labelled = [t for t in turns if t["labels"]["faithfulness_label"] is not None]
    assert len(labelled) == 11
    for t in labelled:
        assert t["labels"]["faithfulness_label"] in (0.0, 0.5, 1.0), t["turn_id"]
        assert t["labels"]["citation_quality_label"] in (0.0, 0.5, 1.0), t["turn_id"]
    for t in turns:
        if t["labels"]["faithfulness_label"] is None:
            assert t["labels"]["citation_quality_label"] is None, t["turn_id"]


def test_judge_labels_are_not_all_one_value(turns):
    """A label set with no variance would make kappa meaningless by construction."""
    faith = {t["labels"]["faithfulness_label"] for t in turns
             if t["labels"]["faithfulness_label"] is not None}
    cite = {t["labels"]["citation_quality_label"] for t in turns
            if t["labels"]["citation_quality_label"] is not None}
    assert len(faith) > 1 and len(cite) > 1
