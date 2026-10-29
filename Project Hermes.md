# Project Hermes

Project Hermes is a **local-first voice-assistant starter** for a user-controlled Linux homelab. It combines a FastAPI gateway, Celery/Redis background jobs, local Ollama routing, optional local STT/TTS containers, a capability-based plugin contract, encrypted local records, and tailnet-only access. It is a security-oriented starter rather than a finished consumer assistant: all consequential integrations remain policy-gated and require local operator configuration.

| Deliverable | Location | Purpose |
| --- | --- | --- |
| Architecture and trust boundaries | [`docs/architecture.md`](docs/architecture.md) | Mermaid flow, HA design, network separation, and cryptographic constraints. |
| Runtime configuration | [`config/config.example.yaml`](config/config.example.yaml) | Local models, secrets, network policy, email provider/fallback, plugins, retries, and observability. |
| Encryption module | [`app/core/e2ee.py`](app/core/e2ee.py) | Argon2id-derived AES-256-GCM records plus a reviewed libsignal-sidecar integration boundary. |
| API gateway | [`app/main.py`](app/main.py) | Fail-closed startup, readiness endpoints, correlation IDs, and a disabled-by-default diagnostic router. |
| Plugin framework | [`app/plugins/base.py`](app/plugins/base.py) and [`app/plugins/registry.py`](app/plugins/registry.py) | Manifest, capabilities, approvals, plugin discovery, and optional safe hot reload. |
| Tailscale connector | [`app/services/tailscale_connector.py`](app/services/tailscale_connector.py) | Read-only host-side status checks with explicit subprocess arguments and exponential backoff. |
| Compose deployment | [`deploy/docker-compose.yml`](deploy/docker-compose.yml) | API, worker, plugin host, Redis, Postgres, and optional STT/TTS services. |
| Host hardening preview | [`deploy/harden-host.sh`](deploy/harden-host.sh) | Dry-run-first UFW, auditd, AppArmor, and unattended-update configuration. |

## Security position

> **Do not call this a custom Signal Protocol implementation.** The maintained upstream `libsignal` bindings are Java, Swift, and TypeScript; this Python project does not reimplement the double ratchet. Hermes stores local records with AES-256-GCM and an Argon2id-derived key. If Signal-compatible end-to-end transport is required, deploy a separately reviewed, pinned TypeScript sidecar using `@signalapp/libsignal-client`, then complete interoperability and security testing before enabling it.[1]

The browser component intentionally uses only standard Playwright. It does not include stealth/evasion code, CAPTCHA handling, credential harvesting, verification-code entry, payment interaction, or final-form submission. The current `playwright-stealth` project describes itself as a proof-of-concept for masking automation signals, so it is intentionally excluded.[2]

| Feature | Included starter behavior | Required production control |
| --- | --- | --- |
| Local record encryption | AES-256-GCM with a random nonce and AAD, keyed from Argon2id at boot. | Use an interactive boot secret or hardware-backed secret source; rotate keys and test restores. |
| Transport E2EE | Disabled sidecar adapter boundary only. | Audited client key lifecycle, a pinned TypeScript libsignal sidecar, replay protection, and protocol test vectors. |
| Tailscale access | API exposes `127.0.0.1:8000`; host proxy owns remote ingress. | Tailnet ACLs, tagged service hosts, device enrollment, and periodic access review. |
| High availability | Heartbeat configuration and Tailscale Service-ready topology. | Replicated encrypted data, queued-job idempotency, controlled promotion, and restore drills. |
| Email | OAuth2 IMAP scaffold; destructive actions require an upstream approval ID. | OAuth consent, token vaulting, recipient/domain policy, and user-visible confirmation. |
| Browser support | Allow-listed, attended form preparation only. | Explicit target owner authorization and manual verification/final submission. |

## Deployment choices

| Approach | Tradeoffs | Cost | Setup complexity |
| --- | --- | --- | --- |
| **Existing homelab Linux host** | Keeps models, data, Tailscale identity, and firewall under your control. Availability depends on local power, WAN, and hardware. | Uses existing infrastructure. | Moderate; requires Docker, a local model runtime, Tailscale, and host administration. |
| **Private Linux server you administer** | Provides independent uptime but moves the physical host outside the home. The same Compose and security model apply. | Depends on chosen provider. | Moderate to high; requires hardened remote access, backups, and a latency assessment for voice clients. |

The existing homelab path is the closest match for the stated privacy and offline requirements. The service must be installed on a durable Linux host; this repository is not designed to be left running in an ephemeral development environment.

## Quick start

The following installation is intentionally explicit. Review every setting before execution and do not copy secrets into Git, shell history, screenshots, or chat logs.

```bash
# 1. Create the runtime files and restrict local secrets.
cp .env.example .env
cp config/config.example.yaml config/config.yaml
chmod 0600 .env config/config.yaml

# 2. Edit config/config.yaml for your local Ollama endpoint and selected integrations.
#    In .env, set POSTGRES_PASSWORD and inject HERMES_BOOT_PASSPHRASE securely.

# 3. Validate the Compose shape, then build and start the base services.
docker compose --env-file .env -f deploy/docker-compose.yml config >/dev/null
docker compose --env-file .env -f deploy/docker-compose.yml up --build -d

# 4. Inspect local-only health. The diagnostic endpoint remains disabled.
curl --fail http://127.0.0.1:8000/healthz
curl --fail http://127.0.0.1:8000/readyz
```

For the optional voice profile, replace the STT placeholder image/command with a reviewed local STT runtime suitable for your platform, download a licensed local model, then start the profile with `--profile voice`. Benchmark wake-word latency on the actual microphone hardware before treating the 300 ms objective as met.

## Tailscale ingress and availability

Keep the FastAPI port on loopback. Configure ingress on the host rather than in the Compose stack. Tailscale `serve` can reverse-proxy a loopback service within the tailnet and offers JSON status commands for verification.[3] For two hosts, use a Tailscale Service with tagged service identities and controlled approval; it provides a stable MagicDNS name and TailVIP that can steer traffic across available hosts.[4]

```bash
# Example: run on the host after approving the service identity and ACL policy.
tailscale serve --service=svc:hermes-api --https=443 127.0.0.1:8000
tailscale serve status --json
```

Run the `TailscaleConnector` on the host only. It intentionally allows only `tailscale status --json` and `tailscale serve status --json`; it cannot execute arbitrary shell commands or alter access policy.

## Configuration and secrets

`config/config.example.yaml` names secret references but contains no credentials. The starter resolves only `env:` references, so use environment injection for local testing. A real Vault integration must be implemented and tested explicitly; do not place a `vault:` string in the configuration and assume the code will silently handle it.

| Integration | Supported template | Default safety condition |
| --- | --- | --- |
| Ollama | Local HTTP endpoint only (`127.0.0.1` or Docker host bridge). | Bounded retries and timeouts; no cloud fallback. |
| Gmail | OAuth2 IMAP/SMTP settings. | Destructive actions require a policy-validated approval ID. |
| Outlook | Microsoft Graph OAuth2 settings. | Defined as a fallback configuration; implement Graph tool calls separately. |
| Tailscale | Host CLI status checks and optional API token reference. | No API token is read by the container; no Funnel exposure. |
| Tor | Disabled SOCKS/onion placeholders. | Explicit enablement, healthy proxy check, and allow-listed targets. |
| Browser assistant | Standard Playwright, non-persistent contexts. | Empty target allow-list, manual sensitive fields, no submit/2FA/CAPTCHA. |

## Plugin model

A plugin exports one `PLUGIN` instance that derives from `BasePlugin` and supplies a static `PluginManifest`. The registry validates its capability set against `plugins.permitted_capabilities`; plugins have no exposed arbitrary-shell or unrestricted-network interface. Set `plugins.hot_reload: true` only while developing in an operator-controlled local directory and only for plugins whose manifest has `hot_reload_safe: true`.

```python
from app.plugins.base import BasePlugin, PluginManifest, ToolRequest, ToolResult, PluginExecutionContext

class HomeAutomationPlugin(BasePlugin):
    manifest = PluginManifest(
        plugin_id="home_automation",
        display_name="Home automation",
        version="0.1.0",
        description="Executes policy-approved requests against a local home controller.",
        capabilities={"home.read", "home.control"},
        requires_human_approval=False,
    )

    async def execute(self, request: ToolRequest, context: PluginExecutionContext) -> ToolResult:
        context.require_capability("home.control")
        return ToolResult(status="ok", summary="Command was validated; add controller adapter next.")

PLUGIN = HomeAutomationPlugin()
```

## Host hardening

Run `deploy/harden-host.sh` only after reviewing it from a host console and setting a trusted SSH CIDR. With no arguments it prints a dry-run preview; it changes the host only when invoked with `--apply`. The script defaults inbound traffic to deny, allows loopback and the trusted administration range, permits tailnet ingress on `tailscale0`, denies direct port 8000 exposure, enables auditd command-execution logs, and verifies AppArmor. Its audit rule is intentionally high-volume; provision log storage, forwarding, and rotation first.

## Verification performed

The project passes Python syntax compilation and Bash syntax validation. The encryption test suite verifies a normal round trip, rejection on AAD mismatch, and rejection of tampered ciphertext envelopes.

```bash
PYTHONPATH=. python3 -m unittest tests/test_e2ee.py -v
```

## References

[1] [Signal — `libsignal` repository](https://github.com/signalapp/libsignal)  
[2] [PyPI — `playwright-stealth` 2.0.3](https://pypi.org/project/playwright-stealth/)  
[3] [Tailscale `serve` command reference](https://tailscale.com/docs/reference/tailscale-cli/serve)  
[4] [Tailscale Services documentation](https://tailscale.com/docs/features/tailscale-services)
