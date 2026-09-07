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


def test_the_policy_names_both_stages_and_their_measured_scores():
    stage = POLICY["stage"]
    assert stage["preferred"] and stage["fallback"]
    measured = stage["measured_on_heldout_v2"]
    for name in (stage["preferred"], stage["fallback"]):
        assert name in measured, f"{name} ships with no held-out measurement beside it"
        assert "precision" in measured[name] and "recall" in measured[name]


def test_with_a_key_the_preferred_stage_is_used():
    out = _resolve({"EVAL_MODEL_API_KEY": "not-a-real-key"})
    assert out.stdout.strip() == POLICY["stage"]["preferred"], out.stderr[-300:]


def test_without_a_key_it_falls_back_to_the_local_stage():
    out = _resolve({})
    assert out.stdout.strip() == POLICY["stage"]["fallback"], out.stderr[-300:]


def test_the_downgrade_is_announced_not_silent():
    """A guardrail quietly running a weaker stage than its policy names is the drift this
    repository exists to catch."""
    out = _resolve({})
    assert "falls back" in out.stderr, out.stderr[-300:]


def test_a_missing_key_never_disables_the_stage_entirely():
    out = _resolve({})
    assert out.stdout.strip() not in ("", "none"), "a missing key must not fail open"
