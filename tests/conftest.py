import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def turns() -> list[dict]:
    return json.loads((ROOT / "data" / "turns.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def corpus():
    from clinical_agent.rag import Corpus

    return Corpus.load(ROOT / "data" / "corpus")
