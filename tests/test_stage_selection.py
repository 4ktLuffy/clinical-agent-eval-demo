"""The policy names the stage; a missing key downgrades it loudly, never silently."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY = yaml.safe_load((ROOT / "data" / "policy.yaml").read_text(encoding="utf-8"))


def _resolve(env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0,'src');"
         "from clinical_agent.semantic import stage_from_policy; print(stage_from_policy())"],
        cwd=ROOT, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", **env})


def test_the_policy_names_every_selectable_stage_with_its_measured_scores():
    stage = POLICY["stage"]
    assert stage["default"] in stage["selectable"]
    assert stage["fallback"] in stage["selectable"]
    measured = stage["measured_on_heldout_v2"]
    for name in stage["selectable"]:
        assert name in measured, f"{name} ships with no held-out measurement beside it"
        assert "precision" in measured[name] and "recall" in measured[name]


def test_the_default_stage_needs_no_key():
    """MiniLM is the default precisely so the shipped guardrail does not depend on a
    provider being reachable."""
    assert POLICY["stage"]["default"] != POLICY["stage"]["requires_key_for"]
    assert _resolve({}).stdout.strip() == POLICY["stage"]["default"]
    assert _resolve({"EVAL_MODEL_API_KEY": "k"}).stdout.strip() == POLICY["stage"]["default"]


def test_the_llm_stage_is_selectable_but_only_with_a_key():
    llm = POLICY["stage"]["requires_key_for"]
    with_key = _resolve({"CLINICAL_STAGE": llm, "EVAL_MODEL_API_KEY": "k"})
    assert with_key.stdout.strip() == llm, with_key.stderr[-300:]
    without = _resolve({"CLINICAL_STAGE": llm})
    assert without.stdout.strip() == POLICY["stage"]["fallback"], without.stderr[-300:]


def test_the_downgrade_is_announced_not_silent():
    """A guardrail quietly running a weaker stage than asked for is the drift this
    repository exists to catch."""
    out = _resolve({"CLINICAL_STAGE": POLICY["stage"]["requires_key_for"]})
    assert "falls back" in out.stderr, out.stderr[-300:]


def test_a_missing_key_never_disables_the_stage_entirely():
    out = _resolve({})
    assert out.stdout.strip() not in ("", "none"), "a missing key must not fail open"
