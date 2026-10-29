"""Local plugin registry with manifest validation and optional safe hot reload."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import AsyncIterator

from watchfiles import Change, awatch

from app.plugins.base import BasePlugin


class PluginRegistrationError(RuntimeError):
    """Raised when a plugin cannot meet the strict local registration contract."""


@dataclass
class RegisteredPlugin:
    plugin: BasePlugin
    path: Path
    sha256: str


class PluginRegistry:
    """Keep an operator-approved registry of plugin instances by manifest ID."""

    def __init__(self, directory: Path, *, allowed_capabilities: set[str], hot_reload: bool = False) -> None:
        self.directory = directory
        self.allowed_capabilities = allowed_capabilities
        self.hot_reload = hot_reload
        self._plugins: dict[str, RegisteredPlugin] = {}
        self._by_path: dict[Path, str] = {}

    @property
    def plugins(self) -> dict[str, BasePlugin]:
        return {plugin_id: registered.plugin for plugin_id, registered in self._plugins.items()}

    async def discover(self) -> dict[str, BasePlugin]:
        """Load every visible Python source file in a local operator-controlled directory."""
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.directory.glob("*.py")):
            if not path.name.startswith("_"):
                await self._load(path, is_reload=False)
        return self.plugins

    async def watch(self) -> None:
        """Watch for create/modify/delete events when hot reload is explicitly enabled."""
        if not self.hot_reload:
            return
        async for changes in awatch(self.directory):
            for change, raw_path in changes:
                path = Path(raw_path)
                if path.suffix != ".py" or path.name.startswith("_"):
                    continue
                if change == Change.deleted:
                    await self._unload_path(path)
                elif change in {Change.added, Change.modified}:
                    await self._load(path, is_reload=True)

    async def _load(self, path: Path, *, is_reload: bool) -> None:
        if not path.is_file():
            return
        existing_id = self._by_path.get(path)
        if is_reload and existing_id:
            existing = self._plugins[existing_id]
            if not existing.plugin.manifest.hot_reload_safe:
                return
            await existing.plugin.shutdown()
            self._plugins.pop(existing_id, None)
            self._by_path.pop(path, None)
        plugin = self._instantiate(path)
        manifest = plugin.manifest
        unexpected = manifest.capabilities - self.allowed_capabilities
        if unexpected:
            raise PluginRegistrationError(f"Plugin {manifest.plugin_id} declares denied capabilities: {sorted(unexpected)}")
        if manifest.plugin_id in self._plugins:
            raise PluginRegistrationError(f"Duplicate plugin_id: {manifest.plugin_id}")
        health = await plugin.health()
        if health.get("status") != "ok":
            raise PluginRegistrationError(f"Plugin {manifest.plugin_id} failed its health check.")
        registered = RegisteredPlugin(plugin=plugin, path=path, sha256=self._digest(path))
        self._plugins[manifest.plugin_id] = registered
        self._by_path[path] = manifest.plugin_id

    async def _unload_path(self, path: Path) -> None:
        plugin_id = self._by_path.pop(path, None)
        if not plugin_id:
            return
        registered = self._plugins.pop(plugin_id)
        await registered.plugin.shutdown()

    @staticmethod
    def _instantiate(path: Path) -> BasePlugin:
        module_name = f"hermes_local_plugin_{hashlib.sha256(str(path).encode()).hexdigest()[:16]}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if not spec or not spec.loader:
            raise PluginRegistrationError(f"Could not construct module spec for {path.name}.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        candidate = getattr(module, "PLUGIN", None)
        if not isinstance(candidate, BasePlugin):
            raise PluginRegistrationError(f"{path.name} must export PLUGIN = <BasePlugin instance>.")
        return candidate

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
