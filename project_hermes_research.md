# Project Hermes research notes

## libsignal — official source

- **Source:** https://github.com/signalapp/libsignal
- **Checked:** 2026-08-21
- The official `signalapp/libsignal` repository states that its platform-agnostic API is exposed as **Java, Swift, and TypeScript** libraries, with Rust implementations underneath.
- Signal publishes `@signalapp/libsignal-client` with native libraries for Windows, macOS, and Debian-flavored Linux. Its Linux/Windows ARM64 builds are described as experimental.
- The repository does **not** present an officially supported Python binding. For this Python/FastAPI design, the codebase will therefore use a versioned **local encryption adapter** built on a reviewed cryptography library for at-rest protection and a transport interface. A separately deployed, pinned Node/TypeScript sidecar should be used if interoperable Signal double-ratchet functionality is later required.
- This is intentionally not presented as an independent reimplementation of Signal Protocol; cryptographic protocol use requires independent security review, test vectors, version pinning, and client-side key ownership.

## Initial deployment conclusion

Project Hermes requires Docker, host firewall controls, and local-network binding. It should run on the user’s homelab or other full Linux host, rather than a managed lightweight web host. Docker Compose is appropriate for its multi-service topology.

## Safety boundary

The requested signup component will be scoped to an **operator-attended, compliance-first form assistant**. It will not use stealth/evasion, solve or bypass CAPTCHAs, or automate account verification. It will stop before a verification/2FA step and require the user to enter the code locally.

## Playwright — official source

- **Source:** https://playwright.dev/python/docs/library
- **Checked:** 2026-08-21
- Playwright Python supports synchronous and asynchronous APIs; the official guidance recommends the asynchronous API for an asyncio-based modern service.
- The Python API is not thread-safe; a worker must create a separate Playwright instance per thread. The starter will use an asynchronous worker and a new, non-persistent browser context for each job.
- Browser contexts provide isolated sessions and the documentation recommends one context per independent session.
- The implementation will rely on normal locator/actionability waits, bounded timeouts, and operator-approved allow-listed targets. It will not include `playwright-stealth`, anti-detection techniques, CAPTCHA solvers, 2FA interception, or any bypass mechanism.

## Implementation implication

The browser module will be a **consent-preserving assistant**: it can open an approved first-party page and fill non-sensitive, user-provided fields. It must pause before verification, CAPTCHA, payment, or final account-submission actions and wait for a local operator approval event. It will keep an auditable job record without storing secrets.

## Tailscale — official sources

| Topic | Verified finding | Source |
| --- | --- | --- |
| Administrative automation | The Tailscale API supports access tokens with expirations from 1 to 90 days, and supports more narrowly delegated credentials. | https://tailscale.com/docs/reference/tailscale-api |
| Stable high-availability endpoint | Tailscale Services can route a stable MagicDNS name and TailVIP to more than one available host, with traffic steering and access controls. It is an appropriate replacement for a floating IP/DNS-script failover pattern for TCP services. | https://tailscale.com/docs/features/tailscale-services |
| Service host requirements | Service hosts need a tag-based identity and admin approval unless policy enables auto-approval. | https://tailscale.com/docs/features/tailscale-services |
| Local reverse proxy | `tailscale serve` supports secure tailnet-only sharing, reverse proxying only to `http://127.0.0.1`, and status/configuration commands. HTTPS is terminated by the daemon with a provisioned certificate. | https://tailscale.com/docs/reference/tailscale-cli/serve |

The starter will favor a host-managed `tailscale serve`/Services topology instead of placing a privileged Tailscale daemon inside the application containers. It will use a restricted local command wrapper around `tailscale status --json` and `tailscale serve status --json`, never a broad shell-execution interface. The primary API remains bound to loopback; Tailscale acts as the authenticated ingress.

## `playwright-stealth` review

The current PyPI project is `playwright-stealth` **2.0.3**, released 2026-04-04 and requiring Python 3.9+. Its own description characterizes it as a fork and a proof-of-concept that should not be expected to bypass more than simple bot detection. Because its purpose includes suppressing browser automation signals, Project Hermes deliberately does not use it. The implementation uses the official Playwright API only and respects target-site terms, controls, and verification flows.

- **Source:** https://pypi.org/project/playwright-stealth/
- **Checked:** 2026-08-21

