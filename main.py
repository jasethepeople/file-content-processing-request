"""FastAPI entrypoint for Project Hermes.

The API binds to loopback and is intended to be reached through host-managed
Tailscale ingress.  Tool execution is intentionally not exposed here: it must
pass device authentication, E2EE session validation, capability policy, and
human-approval checks in the plugin host.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.core.config import HermesConfig, load_config, resolve_environment_secret
from app.core.e2ee import Argon2idParameters, E2EEManager
from app.services.ollama_router import LocalModelRouter, OllamaClient, OllamaModel, RouteDecision


class RouteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class RouteResponse(BaseModel):
    request_id: str
    decision: RouteDecision


def _build_e2ee(config: HermesConfig) -> E2EEManager:
    encryption = config.security.encryption
    parameters = Argon2idParameters(
        time_cost=encryption.argon2id.get("time_cost", 3),
        memory_cost_kib=encryption.argon2id.get("memory_cost_kib", 65_536),
        parallelism=encryption.argon2id.get("parallelism", 2),
        hash_len=encryption.argon2id.get("hash_len", 32),
    )
    passphrase = resolve_environment_secret(encryption.master_passphrase_secret_ref)
    return E2EEManager(
        passphrase=passphrase,
        salt_path=encryption.salt_path,
        parameters=parameters,
    )


def _build_router(config: HermesConfig) -> tuple[OllamaClient, LocalModelRouter, str]:
    ollama = config.models.get("ollama", {})
    router = config.models.get("router", {})
    base_url = str(ollama.get("base_url", ""))
    client = OllamaClient(base_url)
    router_model = OllamaModel(
        name=str(router.get("model", "")),
        timeout_seconds=float(ollama.get("request_timeout_seconds", 45)),
    )
    return client, LocalModelRouter(client, router_model), str(ollama.get("health_path", "/api/tags"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    app.state.config = config
    app.state.e2ee = _build_e2ee(config)
    app.state.ollama, app.state.router, app.state.ollama_health_path = _build_router(config)
    yield
    app.state.e2ee.destroy()


app = FastAPI(
    title="Project Hermes API",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.middleware("http")
async def correlation_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """Liveness: process and configuration loaded successfully."""
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
async def readyz(request: Request) -> dict[str, str]:
    """Readiness: the configured local LLM endpoint can respond."""
    healthy = await request.app.state.ollama.health(request.app.state.ollama_health_path)
    if not healthy:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="local_model_unavailable")
    return {"status": "ready"}


@app.post("/internal/router/decision", response_model=RouteResponse, include_in_schema=False)
async def diagnostic_route(request: Request, body: RouteRequest) -> RouteResponse:
    """Temporarily expose the router only for local, authenticated diagnostics.

    This endpoint is disabled by default and never performs a tool action.  A
    production client must instead use the E2EE session protocol and policy
    gateway before an intent can reach the router.
    """
    if os.getenv("HERMES_ENABLE_ROUTER_DIAGNOSTICS", "false").lower() != "true":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if request.headers.get("X-Hermes-Diagnostic-Token") != os.getenv("HERMES_DIAGNOSTIC_TOKEN"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="diagnostic_auth_required")
    decision = await request.app.state.router.select_route(body.text)
    return RouteResponse(request_id=request.state.request_id, decision=decision)
