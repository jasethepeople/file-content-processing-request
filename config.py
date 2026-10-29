"""Validated configuration loader for Project Hermes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, HttpUrl, ValidationError


class EncryptionSettings(BaseModel):
    record_cipher: str = "AES-256-GCM"
    kdf: str = "Argon2id"
    salt_path: Path
    master_passphrase_secret_ref: str
    argon2id: dict[str, int] = Field(default_factory=dict)


class SecuritySettings(BaseModel):
    secrets_backend: str
    encryption: EncryptionSettings


class ApplicationSettings(BaseModel):
    name: str
    environment: str
    api_bind_host: str
    api_bind_port: int = Field(ge=1, le=65535)
    audit_log_path: Path


class HermesConfig(BaseModel):
    application: ApplicationSettings
    security: SecuritySettings
    models: dict[str, Any]
    network: dict[str, Any]
    plugins: dict[str, Any]
    resilience: dict[str, Any]
    observability: dict[str, Any]


def config_path() -> Path:
    """Return the configured YAML path without falling back to insecure defaults."""
    return Path(os.getenv("HERMES_CONFIG_PATH", "/app/config/config.yaml"))


def load_config(path: Path | None = None) -> HermesConfig:
    """Read and validate the YAML configuration file."""
    selected = path or config_path()
    if not selected.exists():
        raise RuntimeError(f"Hermes config is missing: {selected}. Copy config.example.yaml first.")
    try:
        raw = yaml.safe_load(selected.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError("Configuration root must be a YAML mapping.")
        return HermesConfig.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as error:
        raise RuntimeError(f"Hermes config is invalid: {error}") from error


def resolve_environment_secret(reference: str) -> str:
    """Resolve only explicitly configured environment references in this starter.

    Vault resolution is deliberately not silently emulated.  Configure a reviewed
    Vault client before using `vault:` references in production.
    """
    if not reference.startswith("env:"):
        raise RuntimeError("This starter resolves only env: secret references.")
    variable_name = reference.removeprefix("env:")
    value = os.getenv(variable_name)
    if not value:
        raise RuntimeError(f"Required secret is unset: {variable_name}")
    return value
