"""Append-only audit of every FHIR access, hash-chained.

One line per call, written before the response is returned, so a crash mid-call still
leaves the attempt on the record. The file is opened in append mode and never rewritten;
nothing in this package deletes or edits an existing line.

"Append-only" is a claim about intent unless something can detect a breach of it, so each
row carries the hash of the row before it. Editing, reordering or deleting any line breaks
the chain from that point on, and ``verify_chain`` says exactly where. It does not stop a
determined attacker who can rewrite the whole file -- for that the chain head has to be
anchored somewhere the attacker cannot reach -- but it turns silent tampering into a
detectable event, which is the property an incident review needs.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

GENESIS = "0" * 64

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


def row_hash(row: dict, prev_hash: str) -> str:
    """Hash of a row's content bound to its predecessor.

    ``entry_hash`` is excluded from its own input, and the payload is serialised with
    sorted keys so the digest does not depend on dict ordering.
    """
    payload = {k: v for k, v in row.items() if k != "entry_hash"}
    payload["prev_hash"] = prev_hash
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ChainBroken(Exception):
    """Raised by verify_chain when the audit file does not verify."""


class AuditLog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._head = self._existing_head()

    def _existing_head(self) -> str:
        """Continue an existing chain rather than starting a second one in the file."""
        if not self.path.exists():
            return GENESIS
        last = None
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                last = line
        if last is None:
            return GENESIS
        try:
            return json.loads(last).get("entry_hash", GENESIS)
        except json.JSONDecodeError:
            return GENESIS

    def write(self, entry: AuditEntry) -> dict:
        row = entry.as_row()
        row["prev_hash"] = self._head
        row["entry_hash"] = row_hash(row, self._head)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
            handle.flush()
        self._head = row["entry_hash"]
        return row

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]


def verify_chain(path: Path) -> tuple[bool, str]:
    """Verify every row links to the one before it.

    Returns (ok, message). The message names the first line that fails and why, because
    "the audit log is corrupt" is not an actionable finding and "line 41 was edited" is.
    """
    path = Path(path)
    if not path.exists():
        return False, f"no audit file at {path}"
    prev = GENESIS
    count = 0
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            return False, f"line {number}: not valid JSON ({exc.msg})"
        if row.get("prev_hash") != prev:
            return False, (
                f"line {number}: prev_hash {row.get('prev_hash', '')[:12]}... does not match "
                f"the previous row's hash {prev[:12]}... -- a line was inserted, removed or reordered"
            )
        expected = row_hash(row, prev)
        if row.get("entry_hash") != expected:
            return False, (
                f"line {number}: content does not match its hash -- the row was edited "
                f"after it was written"
            )
        prev = row["entry_hash"]
        count += 1
    return True, f"chain intact across {count} entries"
