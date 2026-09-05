"""Sync facade over a real MCP stdio session.

The agent talks to the EHR through a subprocess, not by importing ehr_server, so the
integration seam is a real process boundary and a tool error is a real error. One
asyncio loop runs on a daemon thread; each public method submits a coroutine to it.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

CALL_TIMEOUT_S = 20.0


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: dict | None
    error: str | None


def _src_dir() -> Path:
    return Path(__file__).resolve().parent.parent


class EHRTools:
    """Sync facade over the fixture EHR server (offline path)."""

    module = "clinical_agent.ehr_server"
    extra_env: dict[str, str] = {}

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None

    def __enter__(self) -> "EHRTools":
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._submit(self._open()).result(timeout=CALL_TIMEOUT_S)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._loop is None:
            return
        try:
            self._submit(self._close()).result(timeout=CALL_TIMEOUT_S)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._loop.close()
        self._loop = None

    def _submit(self, coro):
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _open(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(_src_dir()), env.get("PYTHONPATH", "")]
        ).strip(os.pathsep)
        env.update(self.extra_env)
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", self.module],
            env=env,
        )
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()

    async def _close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._session = None

    async def _call(self, name: str, args: dict) -> dict:
        assert self._session is not None
        response = await self._session.call_tool(name, args)
        for block in response.content:
            if getattr(block, "type", None) == "text":
                return json.loads(block.text)
        raise RuntimeError(f"tool {name} returned no text content")

    def _invoke(self, name: str, args: dict) -> ToolResult:
        try:
            payload = self._submit(self._call(name, args)).result(timeout=CALL_TIMEOUT_S)
        except Exception as exc:  # a tool call must never raise into the agent loop
            return ToolResult(ok=False, data=None, error=f"{type(exc).__name__}: {exc}")
        if payload.get("ok"):
            return ToolResult(ok=True, data=payload, error=None)
        return ToolResult(ok=False, data=None, error=str(payload.get("error", "unknown tool error")))

    def patient_lookup(self, mrn: str) -> ToolResult:
        return self._invoke("patient_lookup", {"mrn": mrn})

    def list_slots(self, specialty: str) -> ToolResult:
        return self._invoke("list_slots", {"specialty": specialty})

    def book_appointment(self, mrn: str, slot_id: str) -> ToolResult:
        return self._invoke("book_appointment", {"mrn": mrn, "slot_id": slot_id})

    def call(self, name: str, args: dict) -> ToolResult:
        if name not in {"patient_lookup", "list_slots", "book_appointment"}:
            return ToolResult(ok=False, data=None, error=f"unknown tool {name}")
        return self._invoke(name, args)


class ScopedFhirTools(EHRTools):
    """Sync facade over the patient-scoped FHIR MCP server.

    The patient scope is handed to the subprocess as environment, so the server process
    physically cannot address another patient: no tool takes a patient id.
    """

    module = "clinical_agent.fhir_mcp_server"
    TOOLS = (
        "patient_lookup",
        "upcoming_appointments",
        "active_medications",
        "recent_encounters",
        "schedule_appointment",
        "cancel_appointment",
    )

    def __init__(self, fhir_url: str, patient_id: str, session_id: str, actor: str = "agent") -> None:
        super().__init__()
        self.extra_env = {
            "CLINICAL_AGENT_FHIR_URL": fhir_url,
            "CLINICAL_AGENT_PATIENT_ID": patient_id,
            "CLINICAL_AGENT_SESSION_ID": session_id,
            "CLINICAL_AGENT_ACTOR": actor,
        }
        self.patient_id = patient_id
        self.session_id = session_id

    def call(self, name: str, args: dict) -> ToolResult:
        if name not in self.TOOLS:
            return ToolResult(ok=False, data=None, error=f"unknown tool {name}")
        return self._invoke(name, args)
