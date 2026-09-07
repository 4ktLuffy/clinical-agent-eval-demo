"""The PHI lint must catch real identifiers and not ordinary numbers.

A pattern that fires on a latency float trains everyone to ignore it, and a pattern that
fires on nothing is decoration. Both directions are asserted here.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("phi_lint", ROOT / "scripts" / "phi_lint.py")
phi_lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phi_lint)

MUST_MATCH = [
    ("uk-phone", "call the clinic on 0161 496 0000 please"),
    ("uk-phone", "ring 07700 900123 after four"),
    ("us-ssn", "the number is 078-05-1120"),
    ("email", "write to a.patient@example.com"),
    ("uk-dob", "born 12/03/1954"),
    ("mrn", "MRN 40071923"),
]

MUST_NOT_MATCH = [
    'the latency was 2680.0604999880306 ms',
    '"latency_p50_ms": 1229.5827090274543',
    '"tokens_per_turn": 899.0',
    "take 2 tablets twice a day for 7 days",
    "blood pressure was 130 over 80",
    "version 0.2.0 of the harness",
    # A sha256 from the audit chain, read as a phone number until the hex-blob suppressor.
    '"prev_hash": "00172385808c23ecf0dccfa4e7b1a2c3d4e5f60718293a4b5c6d7e8f90a1b2c3"',
    # An FDA application number inside an RxNorm display string, in the CI fixture.
    '"display":"NDA021457 200 ACTUAT albuterol 0.09 MG"',
]


def _hits(text: str):
    return [name for name, pattern in phi_lint.PATTERNS if pattern.search(text)]


def test_real_identifier_shapes_are_caught():
    for expected, text in MUST_MATCH:
        assert expected in _hits(text), f"{expected} missed in {text!r}"


def test_ordinary_numbers_are_not_flagged():
    """The float that broke this: a report's latency read as a UK phone number, because
    \\b treats the decimal point as a word boundary."""
    for text in MUST_NOT_MATCH:
        assert not _hits(text), f"false positive on {text!r}: {_hits(text)}"
