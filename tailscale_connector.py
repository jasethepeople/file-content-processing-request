"""Constrained host-side Tailscale connector.

Run this module on the Linux host, not in an unprivileged application container.
It intentionally permits only read-only status commands.  Service advertisement,
ACL changes, and daemon lifecycle operations stay under administrator control.
"""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from typing import Any, Sequence


class TailscaleError(RuntimeError):
    """Raised when a bounded Tailscale CLI invocation fails."""


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    stdout: str
    stderr: str
    returncode: int


class TailscaleConnector:
    """Execute a strict allow-list of Tailscale read-only status commands."""

    _STATUS: tuple[str, ...] = ("tailscale", "status", "--json")
    _SERVE_STATUS: tuple[str, ...] = ("tailscale", "serve", "status", "--json")

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        max_attempts: int = 4,
        initial_backoff_seconds: float = 0.5,
        max_backoff_seconds: float = 8.0,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.initial_backoff_seconds = initial_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds

    async def status(self) -> dict[str, Any]:
        """Return parsed `tailscale status --json` output."""
        return self._decode(await self._run_with_retry(self._STATUS))

    async def serve_status(self) -> dict[str, Any]:
        """Return parsed `tailscale serve status --json` output."""
        return self._decode(await self._run_with_retry(self._SERVE_STATUS))

    async def self_online(self) -> bool:
        """Return a conservative health indication from the local daemon's status."""
        status = await self.status()
        backend_state = str(status.get("BackendState", ""))
        return backend_state.lower() == "running"

    async def _run_with_retry(self, command: Sequence[str]) -> CommandResult:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = await self._run_once(command)
                if result.returncode == 0:
                    return result
                last_error = TailscaleError(self._redact_error(result.stderr))
            except (OSError, asyncio.TimeoutError, TailscaleError) as error:
                last_error = error
            if attempt < self.max_attempts:
                cap = min(self.max_backoff_seconds, self.initial_backoff_seconds * (2 ** (attempt - 1)))
                await asyncio.sleep(random.uniform(0, cap))
        raise TailscaleError("Tailscale status unavailable after bounded retries.") from last_error

    async def _run_once(self, command: Sequence[str]) -> CommandResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
        except FileNotFoundError as error:
            raise TailscaleError("The Tailscale CLI is not installed on this host.") from error
        return CommandResult(
            command=tuple(command),
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            returncode=process.returncode or 0,
        )

    @staticmethod
    def _decode(result: CommandResult) -> dict[str, Any]:
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise TailscaleError("Tailscale returned invalid JSON status output.") from error
        if not isinstance(parsed, dict):
            raise TailscaleError("Tailscale status output has an unexpected shape.")
        return parsed

    @staticmethod
    def _redact_error(stderr: str) -> str:
        # Avoid leaking an arbitrary daemon error to an API client or audit stream.
        return stderr.strip()[:300] or "Tailscale command failed."
