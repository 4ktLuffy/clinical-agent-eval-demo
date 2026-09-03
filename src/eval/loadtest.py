"""Async load generator with fault injection.

The point is not the throughput number. The point is that each detector is proved by an
injected fault that makes it fire, and by a clean baseline run in which it stays quiet.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from clinical_agent.detectors import DetectorConfig, run_detectors
from clinical_agent.guardrail import classify
from clinical_agent.rag import RETRIEVAL_THRESHOLD, Corpus
from clinical_agent.telemetry import percentile

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Fault:
    """Everything defaults to off; the baseline run injects nothing."""

    name: str = "baseline"
    tool_error_rate: float = 0.0
    latency_extra_ms: float = 0.0
    latency_from_fraction: float = 1.0     # cliff begins after this fraction of sessions
    suppress_guardrail_from: float = 1.0   # guardrail goes quiet after this fraction
    cross_patient_rate: float = 0.0


@dataclass
class TurnRecord:
    session_id: str
    total_ms: float
    tool_called: bool
    tool_error: bool
    refused: bool
    scope_violation: bool


async def run_session(index: int, total: int, conversation: dict, corpus: Corpus,
                      fault: Fault, rng: random.Random,
                      out: list[TurnRecord]) -> None:
    progress = index / max(1, total)
    session_id = f"s{index:05d}"
    for turn in conversation["turns"]:
        started = time.perf_counter()

        retrieved = corpus.retrieve(turn["text"], k=4)
        top = retrieved[0].score if retrieved else 0.0

        tool_called = turn["kind"] in ("medications", "appointments")
        tool_error = tool_called and rng.random() < fault.tool_error_rate

        guardrail_on = progress < fault.suppress_guardrail_from
        decision = classify(turn["text"], turn["mock_draft"], top,
                            "tool call failed" if tool_error else None,
                            enabled=guardrail_on)

        scope_violation = rng.random() < fault.cross_patient_rate

        # Simulated downstream latency. The cliff is what the detector has to catch.
        base_ms = 1.5 + rng.random() * 2.0
        if progress >= fault.latency_from_fraction:
            base_ms += fault.latency_extra_ms
        await asyncio.sleep(base_ms / 1000.0)

        out.append(TurnRecord(
            session_id=session_id,
            total_ms=(time.perf_counter() - started) * 1000,
            tool_called=tool_called,
            tool_error=tool_error,
            refused=decision.refused,
            scope_violation=scope_violation,
        ))


async def run_load(conversations: list[dict], corpus: Corpus, sessions: int,
                   concurrency: int, fault: Fault, seed: int) -> list[dict]:
    rng = random.Random(seed)
    records: list[TurnRecord] = []
    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(index: int) -> None:
        async with semaphore:
            await run_session(index, sessions,
                              conversations[index % len(conversations)],
                              corpus, fault, random.Random(seed + index), records)

    await asyncio.gather(*(guarded(i) for i in range(sessions)))
    records.sort(key=lambda r: r.session_id)
    return [asdict(r) for r in records]


def summarise(records: list[dict]) -> dict:
    values = [r["total_ms"] for r in records]
    tool_calls = [r for r in records if r["tool_called"]]
    return {
        "turns": len(records),
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "tool_calls": len(tool_calls),
        "tool_error_rate": (sum(1 for r in tool_calls if r["tool_error"]) / len(tool_calls)) if tool_calls else 0.0,
        "refusal_rate": sum(1 for r in records if r["refused"]) / len(records) if records else 0.0,
        "scope_violations": sum(1 for r in records if r["scope_violation"]),
    }


SCENARIOS = [
    Fault(name="baseline"),
    Fault(name="tool_error_spike", tool_error_rate=0.35),
    Fault(name="latency_cliff", latency_extra_ms=600.0, latency_from_fraction=0.75),
    Fault(name="guardrail_silently_off", suppress_guardrail_from=0.75),
    Fault(name="cross_patient_probe", cross_patient_rate=0.004),
]

# Which detector each scenario is designed to trip. baseline must trip nothing.
EXPECTED = {
    "baseline": None,
    "tool_error_spike": "tool_error_rate_spike",
    "latency_cliff": "latency_cliff",
    "guardrail_silently_off": "refusal_rate_drift",
    "cross_patient_probe": "cross_patient_attempt",
}


def render_html(report: dict) -> str:
    def rows(entries):
        return "\n".join(entries)

    scenario_rows = []
    for entry in report["scenarios"]:
        fired = entry["detectors_fired"]
        expected = entry["expected_detector"]
        verdict_ok = (expected is None and not fired) or (expected in fired)
        scenario_rows.append(
            f"<tr class='{'ok' if verdict_ok else 'bad'}'>"
            f"<td><code>{entry['fault']}</code></td>"
            f"<td>{entry['summary']['turns']}</td>"
            f"<td>{entry['summary']['p50_ms']:.2f}</td>"
            f"<td>{entry['summary']['p95_ms']:.2f}</td>"
            f"<td>{entry['summary']['p99_ms']:.2f}</td>"
            f"<td>{entry['summary']['refusal_rate'] * 100:.1f}%</td>"
            f"<td>{entry['summary']['tool_error_rate'] * 100:.1f}%</td>"
            f"<td>{expected or '<em>none</em>'}</td>"
            f"<td>{'<br>'.join(f'<code>{k}</code>' for k in fired) or '<em>quiet</em>'}</td>"
            f"<td>{'PASS' if verdict_ok else 'FAIL'}</td></tr>"
        )

    alert_rows = [
        f"<tr><td><code>{entry['fault']}</code></td><td><code>{name}</code></td><td>{text}</td></tr>"
        for entry in report["scenarios"] for name, text in entry["alerts"].items()
    ]

    return f"""<!doctype html>
<meta charset="utf-8">
<title>Load and detector report</title>
<style>
  body {{ font: 14px/1.5 -apple-system, system-ui, sans-serif; margin: 2rem auto; max-width: 1100px;
         color: #1a1a1a; background: #fff; }}
  h1 {{ font-size: 1.4rem; }} h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ border: 1px solid #ddd; padding: .4rem .55rem; text-align: left; vertical-align: top; }}
  th {{ background: #f5f5f5; }}
  tr.ok td:last-child {{ color: #0a6b2e; font-weight: 600; }}
  tr.bad td:last-child {{ color: #a11; font-weight: 600; }}
  code {{ background: #f3f3f3; padding: 0 .25rem; }}
  .note {{ color: #555; }}
</style>
<h1>Load and detector report</h1>
<p class="note">
  {report['sessions']} concurrent synthetic sessions per scenario, concurrency
  {report['concurrency']}, mock model path, generated {report['run_date']}.
  Every session is synthetic and no real record is involved. Latency here is harness and
  simulated downstream time, not model time.
</p>
<h2>Scenarios</h2>
<p class="note">Each row injects one fault. The detector named in <em>expected</em> must fire;
the baseline row must stay quiet. A row is PASS only if that held.</p>
<table>
<tr><th>Fault</th><th>Turns</th><th>p50 ms</th><th>p95 ms</th><th>p99 ms</th>
    <th>Refusal</th><th>Tool errors</th><th>Expected</th><th>Fired</th><th>Verdict</th></tr>
{rows(scenario_rows)}
</table>
<h2>Alerts raised</h2>
<table>
<tr><th>Fault</th><th>Detector</th><th>Alert</th></tr>
{rows(alert_rows) or '<tr><td colspan=3><em>none</em></td></tr>'}
</table>
<h2>Detector thresholds</h2>
<p class="note">These rules are ours. No vendor publishes a rule set; only the outcome.</p>
<table>
<tr><th>Setting</th><th>Value</th></tr>
{rows(f"<tr><td><code>{k}</code></td><td>{v}</td></tr>" for k, v in report['detector_config'].items())}
</table>
"""


async def amain(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.loadtest")
    parser.add_argument("--sessions", type=int, default=2000)
    parser.add_argument("--concurrency", type=int, default=250)
    parser.add_argument("--seed", type=int, default=20260903)
    parser.add_argument("--out", type=Path, default=ROOT / "reports")
    args = parser.parse_args(argv)

    conversations = json.loads((ROOT / "data" / "conversations.json").read_text(encoding="utf-8"))
    corpus = Corpus.load(ROOT / "data" / "corpus")
    cfg = DetectorConfig()

    scenarios = []
    for fault in SCENARIOS:
        started = time.perf_counter()
        records = await run_load(conversations, corpus, args.sessions,
                                 args.concurrency, fault, args.seed)
        alerts = run_detectors(records, cfg)
        expected = EXPECTED[fault.name]
        scenarios.append({
            "fault": fault.name,
            "wall_s": time.perf_counter() - started,
            "summary": summarise(records),
            "alerts": alerts,
            "detectors_fired": sorted(alerts),
            "expected_detector": expected,
        })
        verdict = "quiet" if expected is None else ("fired" if expected in alerts else "DID NOT FIRE")
        print(f"  {fault.name:<24} turns={len(records):<7} "
              f"p95={summarise(records)['p95_ms']:.2f}ms  expected={expected or 'nothing'}  -> {verdict}")

    report = {
        "sessions": args.sessions,
        "concurrency": args.concurrency,
        "run_date": date.today().isoformat(),
        "detector_config": asdict(cfg),
        "scenarios": scenarios,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "load-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.out / "load-report.html").write_text(render_html(report), encoding="utf-8")
    print(f"\nwrote {args.out / 'load-report.html'}")

    failures = [
        s["fault"] for s in scenarios
        if (s["expected_detector"] is None and s["detectors_fired"])
        or (s["expected_detector"] is not None and s["expected_detector"] not in s["detectors_fired"])
    ]
    if failures:
        print("DETECTOR PROOF FAILED for: " + ", ".join(failures), file=sys.stderr)
        return 1
    print("every detector fired on its injected fault, and the baseline stayed quiet")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(amain(argv))


if __name__ == "__main__":
    sys.exit(main())
