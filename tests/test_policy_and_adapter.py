"""The policy is data, and the agent is an argument. Both must be swappable, and neither
may fail quietly."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clinical_agent.adapter import build_adapter  # noqa: E402
from clinical_agent.guardrail import POLICY, REFUSAL_CATEGORIES  # noqa: E402


def test_policy_file_drives_the_categories():
    raw = yaml.safe_load((ROOT / "data" / "policy.yaml").read_text(encoding="utf-8"))
    assert tuple(raw["refusal_categories"]) == REFUSAL_CATEGORIES
    assert set(raw["turn_patterns"]) == set(REFUSAL_CATEGORIES)
    assert set(raw["refusal_replies"]) == set(REFUSAL_CATEGORIES)


def test_every_category_has_at_least_one_phrase_and_a_reply():
    for category in REFUSAL_CATEGORIES:
        assert POLICY["turn_patterns"][category], category
        assert POLICY["refusal_replies"][category].strip(), category


def test_a_malformed_policy_raises_rather_than_running_empty(tmp_path, monkeypatch):
    """A guardrail that loads no categories refuses nothing and reports perfect precision
    while doing it. That must be impossible to reach by accident."""
    broken = tmp_path / "policy.yaml"
    broken.write_text("refusal_categories: [prescribe]\n", encoding="utf-8")
    monkeypatch.setenv("CLINICAL_POLICY", str(broken))
    import importlib

    import clinical_agent.guardrail as guardrail

    with pytest.raises(ValueError, match="turn_patterns"):
        importlib.reload(guardrail)
    monkeypatch.delenv("CLINICAL_POLICY")
    importlib.reload(guardrail)


def test_adapter_forms():
    assert build_adapter("mock") is None
    assert build_adapter("openai:some-model").name == "openai:some-model"
    with pytest.raises(ValueError, match="unknown adapter"):
        build_adapter("wat:thing")
    with pytest.raises(ValueError, match="python:package.module:function"):
        build_adapter("python:justamodule")


def test_python_adapter_calls_the_callable():
    import types

    module = types.ModuleType("adapter_probe")
    module.draft = lambda turn, context, tools: f"saw:{turn}"
    sys.modules["adapter_probe"] = module
    adapter = build_adapter("python:adapter_probe:draft")
    assert adapter.draft("hello", "ctx", {}) == "saw:hello"
    del sys.modules["adapter_probe"]
