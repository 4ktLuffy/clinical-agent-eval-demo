"""Append-only audit of every FHIR access.

One line per call, written before the response is returned, so a crash mid-call still
leaves the attempt on the record. The file is opened in append mode and never rewritten;
nothing in this package deletes or edits an existing line.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("CLINICAL_AGENT_AUDIT", "reports/fhir-audit.jsonl"))


@dataclass(frozen=True)
class AuditEntry:
    session_id: str
    actor: str
    patient_scope: str
    operation: str
    resource_type: str
    resource_id: str | None
    outcome: str
    detail: str | None = None

    def as_row(self) -> dict:
        return {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "session_id": self.session_id,
            "actor": self.actor,
            "patient_scope": self.patient_scope,
            "operation": self.operation,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "outcome": self.outcome,
            "detail": self.detail,
        }


class AuditLog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, entry: AuditEntry) -> dict:
        row = entry.as_row()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
            handle.flush()
        return row

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]
