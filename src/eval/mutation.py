"""The check that stops the harness being vacuous.

Removing the guardrail must make the safety numbers worse. If it does not, the
guardrail was not doing the work the scorecard credits it with.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from eval.run import ROOT, evaluate


def main(argv: list[str] | None = None) -> int:
    turns = json.loads((ROOT / "data" / "turns.json").read_text(encoding="utf-8"))
    reports = ROOT / "reports"

    on = evaluate(turns, "mock", True, reports / "mutation-guardrail-on", 1.0)
    off = evaluate(turns, "mock", False, reports / "mutation-guardrail-off", 1.0)

    checks = [
        ("refusal recall", on["refusal"]["recall"], off["refusal"]["recall"]),
        (
            "clinical escalation recall",
            on["clinical_escalation"]["recall"],
            off["clinical_escalation"]["recall"],
        ),
    ]

    failed = []
    for name, before, after in checks:
        delta = after - before
        status = "drops" if after < before else "DID NOT DROP"
        print(f"{name}: {before:.3f} -> {after:.3f} (delta {delta:+.3f}) {status}")
        if after >= before:
            failed.append(name)

    summary = {"checks": [{"name": n, "on": b, "off": a} for n, b, a in checks], "failed": failed}
    (reports / "mutation.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    if failed:
        print(f"MUTATION CHECK FAILED: {', '.join(failed)} did not drop without the guardrail")
        return 1
    print("mutation check passed: both recalls drop when the guardrail is removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
