#!/usr/bin/env bash
# Four turns live, in the order WellSpan's release describes Ana expanding through:
# inbound calls and primary-care scheduling first, then post-discharge follow-up and
# chronic-disease check-in. Mock path, offline, no API key.
set -euo pipefail

cd "$(dirname "$0")/.."
export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"
PY="${PYTHON:-python3}"

"$PY" - <<'PYEOF'
import json
import sys
from pathlib import Path

from clinical_agent.agent import Agent
from clinical_agent.llm import MockClient
from clinical_agent.rag import Corpus
from clinical_agent.tools import EHRTools

ROOT = Path.cwd()
FLOWS = [
    ("T039", "1/4  Inbound FAQ -- grounded answer with citations"),
    ("T047", "2/4  Primary-care scheduling -- through the MCP EHR tools"),
    ("T026", "3/4  Post-discharge follow-up -- URGENT clinical escalation"),
    ("T002", "4/4  Chronic-disease check-in -- completed, prescribing ask refused"),
]

turns = {t["turn_id"]: t for t in json.loads((ROOT / "data" / "turns.json").read_text())}
missing = [tid for tid, _ in FLOWS if tid not in turns]
if missing:
    sys.exit(f"demo cannot run: turns.json is missing {', '.join(missing)}")

corpus = Corpus.load(ROOT / "data" / "corpus")
client = MockClient({tid: turns[tid]["mock_draft"] for tid, _ in FLOWS})

with EHRTools() as tools:
    agent = Agent(client, corpus, tools)
    for turn_id, banner in FLOWS:
        turn = turns[turn_id]
        print("\n" + "=" * 74)
        print(banner)
        print("=" * 74)
        print(f"patient: {turn['text']}")
        result = agent.run_turn(turn)
        print(f"\nagent:   {result.answer}")
        d = result.decision
        print(
            f"\n  citations       : {', '.join(result.citations) or 'none'}"
            f"\n  refused         : {d.refused} {d.refusal_categories or ''}"
            f"\n  clinical esc.   : {d.clinical_severity or 'none'}"
            f" ({d.clinical_system or '-'})"
            f"\n  operational esc.: {d.operational_reason or 'none'}"
            f"\n  latency         : {result.total_ms:.1f} ms"
        )
PYEOF

echo
echo "======================================================================"
echo "Scorecard and anomaly alerts"
echo "======================================================================"
"$PY" -m eval.run --model mock >/dev/null
sed -n '/^## Headline/,/^## Refusal by category/p' reports/scorecard.md | head -n 8
echo
sed -n '/^## Anomaly alerts/,/^## Expected misses/p' reports/scorecard.md | sed '$d'
