"""Encryption primitives and a transport-adapter boundary for Project Hermes.

This module intentionally does not reimplement Signal Protocol.  The official
libsignal project publishes maintained Java, Swift, and TypeScript bindings—not
a supported Python binding.  Local persistence is protected here with an
Argon2id-derived AES-256-GCM key.  Interoperable Signal double-ratchet sessions
belong in a separately deployed and reviewed TypeScript sidecar that uses a
pinned `@signalapp/libsignal-client` version.

Envelope format:
    version (1 byte) || nonce (12 bytes) || ciphertext_and_tag (variable)

The optional AAD must be deterministic on both encryption and decryption.  For
example, use ``b"hermes:entity:<uuid>:v1"`` rather than a timestamp.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import httpx
from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class EncryptionError(RuntimeError):
    """Raised when a ciphertext envelope cannot be authenticated or decoded."""


class TransportEncryptionError(RuntimeError):
    """Raised when the reviewed transport sidecar cannot complete an operation."""


_ENVELOPE_VERSION: Final[bytes] = b"\x01"
_NONCE_LENGTH: Final[int] = 12
_KEY_LENGTH: Final[int] = 32
_SALT_LENGTH: Final[int] = 32


@dataclass(frozen=True)
class Argon2idParameters:
    """Explicit work-factor parameters persisted in configuration, not code."""

    time_cost: int = 3
    memory_cost_kib: int = 65_536
    parallelism: int = 2
    hash_len: int = _KEY_LENGTH


@dataclass(frozen=True)
class CiphertextEnvelope:
    """Serializable authenticated-ciphertext envelope."""

    version: int
    nonce_b64: str
    ciphertext_b64: str

    def as_text(self) -> str:
        """Return a URL-safe transport representation without padding."""
        raw = (
            bytes([self.version])
            + base64.urlsafe_b64decode(self.nonce_b64 + "==")
            + base64.urlsafe_b64decode(self.ciphertext_b64 + "==")
        )
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class E2EEManager:
    """Protect Hermes records at rest and dispatch protocol transport operations.

    ``E2EEManager`` is deliberately named to preserve the application-facing
    contract, but its two responsibilities are separate:

    * local record encryption uses a boot-passphrase-derived symmetric key; and
    * end-to-end transport encryption delegates to ``LibsignalSidecarTransport``.

    The sidecar must be unavailable by default.  Do not enable it until its API,
    pinned package lockfile, key-storage design, and interoperability tests have
    undergone cryptographic review.
    """

    def __init__(
        self,
        *,
        passphrase: str,
        salt_path: Path,
        parameters: Argon2idParameters | None = None,
    ) -> None:
        if len(passphrase) < 12:
            raise ValueError("Boot passphrase must be at least 12 characters.")
        self._parameters = parameters or Argon2idParameters()
        self._salt = self._load_or_create_salt(salt_path)
        self._key = self._derive_key(passphrase.encode("utf-8"), self._salt)
        self._cipher = AESGCM(self._key)

    @staticmethod
    def _load_or_create_salt(salt_path: Path) -> bytes:
        """Load a fixed salt, creating it once using atomic filesystem writes."""
        salt_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            salt = salt_path.read_bytes()
        except FileNotFoundError:
            salt = os.urandom(_SALT_LENGTH)
            temp_path = salt_path.with_suffix(salt_path.suffix + ".tmp")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            try:
                fd = os.open(temp_path, flags, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(salt)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, salt_path)
            except FileExistsError:
                # Another process created the salt; always use its durable value.
                salt = salt_path.read_bytes()
            finally:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
        if len(salt) != _SALT_LENGTH:
            raise EncryptionError(f"Invalid salt length at {salt_path}.")
        return salt

    def _derive_key(self, passphrase: bytes, salt: bytes) -> bytes:
        return hash_secret_raw(
            secret=passphrase,
            salt=salt,
            time_cost=self._parameters.time_cost,
            memory_cost=self._parameters.memory_cost_kib,
            parallelism=self._parameters.parallelism,
            hash_len=self._parameters.hash_len,
            type=Type.ID,
        )

    def encrypt(self, plaintext: bytes, *, aad: bytes) -> CiphertextEnvelope:
        """Encrypt a record using a unique random nonce and authenticated AAD."""
        if not plaintext:
            raise ValueError("Refusing to create an empty encrypted record.")
        if not aad:
            raise ValueError("AAD is required to bind ciphertext to its context.")
        nonce = os.urandom(_NONCE_LENGTH)
        encrypted = self._cipher.encrypt(nonce, plaintext, aad)
        return CiphertextEnvelope(
            version=_ENVELOPE_VERSION[0],
            nonce_b64=base64.urlsafe_b64encode(nonce).decode("ascii").rstrip("="),
            ciphertext_b64=base64.urlsafe_b64encode(encrypted).decode("ascii").rstrip("="),
        )

    def decrypt(self, envelope_text: str, *, aad: bytes) -> bytes:
        """Authenticate and decrypt an envelope; never return partial plaintext."""
        if not aad:
            raise ValueError("AAD is required to bind ciphertext to its context.")
        try:
            padded = envelope_text + "=" * (-len(envelope_text) % 4)
            raw = base64.urlsafe_b64decode(padded)
            version, nonce, ciphertext = raw[:1], raw[1:13], raw[13:]
            if version != _ENVELOPE_VERSION or len(nonce) != _NONCE_LENGTH or not ciphertext:
                raise EncryptionError("Unsupported or malformed ciphertext envelope.")
            return self._cipher.decrypt(nonce, ciphertext, aad)
        except (ValueError, InvalidTag) as error:
            raise EncryptionError("Ciphertext authentication failed.") from error

    def destroy(self) -> None:
        """Best-effort removal of in-memory references on controlled shutdown."""
        self._key = b""
        self._salt = b""
        self._cipher = None  # type: ignore[assignment]


class LibsignalSidecarTransport:
    """Client for a locally reachable, reviewed libsignal TypeScript sidecar.

    This is an explicit integration boundary, not a claimed official libsignal
    HTTP API.  Implement the sidecar contract only after producing protocol test
    vectors.  The API process sends opaque client/session identifiers and opaque
    payload bytes; the sidecar keeps private session state in its own encrypted
    store and returns only opaque ciphertext/plaintext bytes.
    """

    def __init__(self, endpoint: str, *, timeout_seconds: float = 5.0) -> None:
        if not endpoint.startswith("http://127.0.0.1") and not endpoint.startswith("http://signal-sidecar"):
            raise ValueError("Signal sidecar endpoint must remain on a private network.")
        self._endpoint = endpoint.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=min(2.0, timeout_seconds))

    async def encrypt_for_session(self, *, session_id: str, plaintext: bytes) -> bytes:
        """Request encryption from a local sidecar using an auditable placeholder contract."""
        return await self._request(
            "/v1/sessions/encrypt",
            {"session_id": session_id, "payload_b64": base64.b64encode(plaintext).decode("ascii")},
        )

    async def decrypt_for_session(self, *, session_id: str, ciphertext: bytes) -> bytes:
        """Request decryption from a local sidecar using an auditable placeholder contract."""
        return await self._request(
            "/v1/sessions/decrypt",
            {"session_id": session_id, "payload_b64": base64.b64encode(ciphertext).decode("ascii")},
        )

    async def _request(self, path: str, payload: dict[str, str]) -> bytes:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(f"{self._endpoint}{path}", json=payload)
                response.raise_for_status()
                response_payload = response.json()
                result = response_payload["payload_b64"]
                return base64.b64decode(result, validate=True)
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise TransportEncryptionError("Local transport encryption sidecar failed.") from error
