"""Import smoke test for Project Hermes modules."""

import app.main
import app.plugin_host
import app.worker
from app.core.config import HermesConfig
from app.core.e2ee import E2EEManager, LibsignalSidecarTransport
from app.plugins.base import BasePlugin
from app.plugins.registry import PluginRegistry
from app.services.browser_assistant import AttendedBrowserAssistant
from app.services.email_tool import ImapOAuthTool
from app.services.ollama_router import LocalModelRouter
from app.services.tailscale_connector import TailscaleConnector

print("module import smoke test passed")
