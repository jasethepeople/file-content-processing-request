"""Dedicated plugin-host process for Project Hermes."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.core.config import load_config
from app.plugins.registry import PluginRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)


async def run() -> None:
    config = load_config()
    plugin_config = config.plugins
    directory = Path(str(plugin_config["directory"]))
    allowed = set(plugin_config.get("permitted_capabilities", []))
    registry = PluginRegistry(
        directory,
        allowed_capabilities=allowed,
        hot_reload=bool(plugin_config.get("hot_reload", False)),
    )
    loaded = await registry.discover()
    log.info("Loaded %d plugin(s): %s", len(loaded), sorted(loaded))
    if bool(plugin_config.get("hot_reload", False)):
        log.warning("Plugin hot reload is enabled; only operator-controlled local directories are supported.")
        await registry.watch()
    else:
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(run())
