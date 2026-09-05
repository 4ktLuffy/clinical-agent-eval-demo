"""Per-turn telemetry and the anomaly rules.

The four rules below are ours. Hippocratic AI publishes the outcome they want from
monitoring but no rule set, so nothing here is attributed to them. Thresholds are
relative rather than absolute because absolute milliseconds are meaningless on a
mock path.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any, Sequence

from clinical_agent.phi import scrub_for_log


@dataclass(frozen=True)
class AnomalyThresholds:
    window: int = 10
    latency_p95_multiple: float = 3.0
    latency_floor_ms: float = 50.0
    tool_error_burst: int = 2
    refusal_rate_drift: float = 0.25


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = q * (len(ordered) - 1)
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


class TelemetryLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8")
        self.records: list[dict[str, Any]] = []

    def record(self, result: Any) -> dict[str, Any]:
        decision = result.decision
        row = {
            "turn_id": result.turn_id,
            "workflow": result.workflow,
            "model": result.model,
            "total_ms": round(result.total_ms, 3),
            "stage_ms": {k: round(v, 3) for k, v in result.stage_ms.items()},
            "retrieval_top_score": round(result.retrieval_top_score, 4),
            "used_corpus": result.used_corpus,
            "citations": list(result.citations),
            "tool_error": result.tool_error,
            "refused": decision.refused,
            "refusal_categories": list(decision.refusal_categories),
            "clinical_escalation": decision.clinical_escalation,
            "clinical_severity": decision.clinical_severity,
            "clinical_system": decision.clinical_system,
            "operational_escalation": decision.operational_escalation,
            "operational_reason": decision.operational_reason,
        }
        row = scrub_for_log(row)
        self._handle.write(json.dumps(row) + "\n")
        self.records.append(row)
        return row

    def close(self) -> None:
        self._handle.close()


def detect_anomalies(
    records: list[dict[str, Any]],
    thresholds: AnomalyThresholds = AnomalyThresholds(),
) -> list[str]:
    alerts: list[str] = []
    if not records:
        return alerts

    latencies = [r["total_ms"] for r in records]
    run_median = median(latencies)
    window = thresholds.window

    for start in range(0, max(1, len(records) - window + 1)):
        slice_ = records[start : start + window]
        if len(slice_) < window:
            break
        p95 = percentile([r["total_ms"] for r in slice_], 0.95)
        if (
            run_median > 0
            and p95 > thresholds.latency_p95_multiple * run_median
            and p95 > thresholds.latency_floor_ms
        ):
            alerts.append(
                f"latency_drift: turns {slice_[0]['turn_id']}-{slice_[-1]['turn_id']} "
                f"p95 {p95:.1f}ms is over {thresholds.latency_p95_multiple:g}x the run "
                f"median {run_median:.1f}ms"
            )
            break

    for start in range(0, max(1, len(records) - window + 1)):
        slice_ = records[start : start + window]
        errors = [r for r in slice_ if r["tool_error"]]
        if len(errors) >= thresholds.tool_error_burst:
            alerts.append(
                f"tool_error_burst: {len(errors)} tool errors within "
                f"{len(slice_)} turns ({slice_[0]['turn_id']}-{slice_[-1]['turn_id']})"
            )
            break

    baseline = sum(1 for r in records if r["refused"]) / len(records)
    for start in range(0, max(1, len(records) - window + 1)):
        slice_ = records[start : start + window]
        if len(slice_) < window:
            break
        rate = sum(1 for r in slice_ if r["refused"]) / len(slice_)
        if abs(rate - baseline) > thresholds.refusal_rate_drift:
            alerts.append(
                f"refusal_rate_drift: window {slice_[0]['turn_id']}-{slice_[-1]['turn_id']} "
                f"refusal rate {rate:.2f} vs run baseline {baseline:.2f}"
            )
            break

    missing = [r["turn_id"] for r in records if r["used_corpus"] and not r["citations"]]
    if missing:
        alerts.append(
            f"citation_missing: {len(missing)} answer(s) used corpus context with no "
            f"citation ({', '.join(missing[:5])})"
        )

    return alerts


def thresholds_table(thresholds: AnomalyThresholds = AnomalyThresholds()) -> dict[str, Any]:
    return asdict(thresholds)
