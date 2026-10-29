"""Strict plugin contract for Project Hermes.

Plugins are local, operator-installed code.  A manifest is required before a
plugin can be registered, and its declared capabilities must be a subset of the
server policy.  The base class deliberately exposes no general shell executor,
raw secret resolver, or unrestricted HTTP client.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from pydantic import BaseModel, Field


class PluginManifest(BaseModel):
    plugin_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    display_name: str = Field(min_length=3, max_length=120)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")
    description: str = Field(min_length=10, max_length=800)
    capabilities: set[str] = Field(default_factory=set)
    required_secret_refs: set[str] = Field(default_factory=set)
    allowed_domains: set[str] = Field(default_factory=set)
    requires_human_approval: bool = True
    hot_reload_safe: bool = False


class ToolRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    actor_id: str = Field(min_length=3, max_length=128)
    action: str = Field(min_length=2, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = None


class ToolResult(BaseModel):
    status: str = Field(pattern=r"^(ok|denied|needs_approval|failed)$")
    summary: str = Field(max_length=1000)
    data: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


@dataclass(frozen=True)
class PluginExecutionContext:
    """Narrow runtime handle supplied after policy checks complete."""

    request_id: str
    actor_id: str
    granted_capabilities: frozenset[str]
    approved_domains: frozenset[str]
    approval_id: str | None
    deadline: datetime
    metadata: Mapping[str, str] = field(default_factory=dict)

    def require_capability(self, capability: str) -> None:
        if capability not in self.granted_capabilities:
            raise PermissionError(f"Missing plugin capability: {capability}")

    def require_approval(self) -> None:
        if not self.approval_id:
            raise PermissionError("This action requires an unexpired human approval token.")


class BasePlugin(ABC):
    """All plugins must provide a manifest and one bounded async execution entrypoint."""

    @property
    @abstractmethod
    def manifest(self) -> PluginManifest:
        """Return a static manifest; do not resolve secrets in this property."""

    @abstractmethod
    async def execute(self, request: ToolRequest, context: PluginExecutionContext) -> ToolResult:
        """Perform one validated action and return an auditable structured result."""

    async def health(self) -> dict[str, str]:
        """Provide a side-effect-free readiness response for the registry."""
        return {"status": "ok", "plugin_id": self.manifest.plugin_id}

    async def shutdown(self) -> None:
        """Release plugin-managed resources before an approved reload."""
