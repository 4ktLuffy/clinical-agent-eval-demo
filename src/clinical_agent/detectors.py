"""Production detectors. These rules are ours; no vendor publishes a rule set.

Each returns None when quiet and an alert string when it fires. Every one is proved by an
injected fault in the load test rather than asserted to work.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Sequence

from clinical_agent.telemetry import percentile


@dataclass(frozen=True)
class DetectorConfig:
    window: int = 200
    refusal_drift: float = 0.15
    tool_error_rate: float = 0.05
    latency_cliff_multiple: float = 3.0
    latency_floor_ms: float = 5.0


def refusal_rate_drift(records: Sequence[dict], cfg: DetectorConfig) -> str | None:
    """A guardrail that quietly stops firing looks exactly like a quiet day."""
    if len(records) < cfg.window * 2:
        return None
    # Reference is the EARLIEST window, not everything-but-the-tail. A fault that has been
    # running for a while contaminates any trailing baseline and hides itself; comparing
    # against how the run started is the question a deploy actually wants answered.
    head, tail = records[: cfg.window], records[-cfg.window:]
    baseline = sum(1 for r in head if r["refused"]) / len(head)
    rate = sum(1 for r in tail if r["refused"]) / len(tail)
    if abs(rate - baseline) > cfg.refusal_drift:
        return (f"refusal_rate_drift: last {cfg.window} turns at {rate:.1%} "
                f"vs run baseline {baseline:.1%}")
    return None


def tool_error_rate_spike(records: Sequence[dict], cfg: DetectorConfig) -> str | None:
    calls = [r for r in records if r.get("tool_called")]
    if len(calls) < 50:
        return None
    errors = sum(1 for r in calls if r.get("tool_error"))
    rate = errors / len(calls)
    if rate > cfg.tool_error_rate:
        return f"tool_error_rate_spike: {rate:.1%} of {len(calls)} tool calls failed"
    return None


def latency_cliff(records: Sequence[dict], cfg: DetectorConfig) -> str | None:
    if len(records) < cfg.window * 2:
        return None
    # Compare like with like. An earlier version compared the tail p95 against the head
    # *median*, which is two different statistics: under load the queueing tail alone made
    # a healthy system look like a cliff, and at 2,000 sessions it also masked a real one.
    head = [r["total_ms"] for r in records[: cfg.window]]
    tail = [r["total_ms"] for r in records[-cfg.window:]]
    head_p95 = percentile(head, 0.95)
    tail_p95 = percentile(tail, 0.95)
    if (head_p95 > 0 and tail_p95 > cfg.latency_cliff_multiple * head_p95
            and tail_p95 > cfg.latency_floor_ms):
        return (f"latency_cliff: tail p95 {tail_p95:.0f}ms is over "
                f"{cfg.latency_cliff_multiple:g}x the opening p95 {head_p95:.0f}ms")
    return None


def cross_patient_attempt(records: Sequence[dict], cfg: DetectorConfig) -> str | None:
    """Any refused scope violation is a page, not a metric. One is enough."""
    attempts = [r for r in records if r.get("scope_violation")]
    if attempts:
        sessions = sorted({r["session_id"] for r in attempts})[:5]
        return (f"cross_patient_attempt: {len(attempts)} refused scope violation(s) "
                f"in sessions {', '.join(sessions)}")
    return None


DETECTORS = (
    ("refusal_rate_drift", refusal_rate_drift),
    ("tool_error_rate_spike", tool_error_rate_spike),
    ("latency_cliff", latency_cliff),
    ("cross_patient_attempt", cross_patient_attempt),
)


def run_detectors(records: Sequence[dict], cfg: DetectorConfig | None = None) -> dict[str, Any]:
    cfg = cfg or DetectorConfig()
    fired = {}
    for name, fn in DETECTORS:
        alert = fn(records, cfg)
        if alert:
            fired[name] = alert
    return fired
