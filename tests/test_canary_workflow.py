"""A canary with no key must report skipped, never success.

For two scheduled days this workflow finished green in nine seconds having done nothing:
every step was guarded `if: present == 'true'`, and a job whose steps all skip is a
successful job. The README carried its badge. A gate that cannot fail is not a gate.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "canary.yml").read_text(encoding="utf-8"))


def test_the_canary_job_is_gated_at_the_job_level():
    """Job-level, not step-level: that is the difference between a run that reports
    skipped and one that reports success while doing nothing."""
    condition = WORKFLOW["jobs"]["canary"].get("if", "")
    assert "needs.gate.outputs.present" in condition, condition


def test_no_canary_step_references_a_step_from_another_job():
    """`steps.key` lives in the gate job now. An expression naming it from inside the
    canary job evaluates to empty, so the step silently never runs -- which is how the
    key-leak scan and the artifact upload almost got switched off."""
    for step in WORKFLOW["jobs"]["canary"]["steps"]:
        assert "steps.key" not in str(step.get("if", "")), step.get("name") or step.get("uses")


def test_the_keyless_path_says_so_out_loud():
    gate = WORKFLOW["jobs"]["gate"]["steps"]
    warned = [s for s in gate if "::warning::" in str(s.get("run", ""))]
    assert warned, "a keyless canary must annotate the run, not pass quietly"


def test_the_leak_scan_and_upload_survive_a_failing_canary():
    """Both must run on failure: the diff is the artifact worth having when it breaks."""
    steps = WORKFLOW["jobs"]["canary"]["steps"]
    for name in ("No key leaked into the canary output",):
        step = next(s for s in steps if s.get("name") == name)
        assert "always()" in str(step.get("if", "")), name
    upload = next(s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact"))
    assert "always()" in str(upload.get("if", ""))


def test_the_canary_never_writes_to_the_repository():
    text = (ROOT / ".github" / "workflows" / "canary.yml").read_text(encoding="utf-8")
    for forbidden in ("git commit", "git push", "peter-evans/create-pull-request"):
        assert forbidden not in text, forbidden
