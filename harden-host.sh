#!/usr/bin/env bash
# Project Hermes host-hardening script for Ubuntu 24.04 / AppArmor hosts.
#
# Review in a local console before use. It changes host firewall and audit policy
# only with --apply. It assumes Hermes listens only on 127.0.0.1 and Tailscale
# owns remote ingress. Do not run this from an unverified remote session.

set -euo pipefail

APPLY=false
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=true ;;
    --help)
      echo "Usage: sudo HERMES_ADMIN_SSH_CIDR=192.0.2.0/24 $0 [--apply]"
      exit 0
      ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

require_root() {
  if [[ "$EUID" -ne 0 ]]; then
    echo "Run as root: sudo $0 --apply" >&2
    exit 1
  fi
}

run() {
  printf '+ '
  printf '%q ' "$@"
  printf '\n'
  if [[ "$APPLY" == true ]]; then
    "$@"
  fi
}

require_root

if [[ -z "${HERMES_ADMIN_SSH_CIDR:-}" ]]; then
  echo "Set HERMES_ADMIN_SSH_CIDR to your trusted SSH network before running." >&2
  exit 1
fi

if [[ "$APPLY" != true ]]; then
  cat <<'NOTICE'
DRY RUN ONLY. No system changes will be made.

Review these critical assumptions:
  1. You have console or out-of-band access to the host.
  2. Hermes API binds to 127.0.0.1, not a public interface.
  3. Tailscale is installed and authenticated before firewall enforcement.
  4. HERMES_ADMIN_SSH_CIDR is a trusted administrative range.

Re-run with --apply only after confirming each item.
NOTICE
fi

# Keep packages limited to operating-system security controls.
run apt-get update
run apt-get install -y --no-install-recommends ufw auditd apparmor apparmor-utils unattended-upgrades

# UFW is stateful. Outbound traffic is allowed so Tailscale can establish its
# encrypted overlay; inbound access remains deny-by-default except loopback,
# trusted SSH administration, and tailnet ingress through tailscale0.
run ufw --force reset
run ufw default deny incoming
run ufw default allow outgoing
run ufw allow in on lo
run ufw allow from "$HERMES_ADMIN_SSH_CIDR" to any port 22 proto tcp comment 'Hermes trusted administration'
run ufw allow in on tailscale0 to any port 443 proto tcp comment 'Hermes Tailscale HTTPS ingress'
run ufw allow in on tailscale0 to any port 22 proto tcp comment 'Hermes Tailscale SSH administration'
run ufw deny in to any port 8000 proto tcp comment 'Hermes API must remain loopback only'
run ufw logging medium
run ufw --force enable

# Audit every host command execution. This can generate significant event volume;
# forward or rotate /var/log/audit securely and test storage capacity first.
AUDIT_RULES=/etc/audit/rules.d/90-hermes-exec.rules
if [[ "$APPLY" == true ]]; then
  cat >"$AUDIT_RULES" <<'RULES'
# Project Hermes host command-execution audit rule.
-a always,exit -F arch=b64 -S execve -k hermes-exec
-a always,exit -F arch=b32 -S execve -k hermes-exec
RULES
else
  echo "+ write $AUDIT_RULES with execve audit rules"
fi
run augenrules --load
run systemctl enable --now auditd

# AppArmor is enforced when a profile is available. This does not invent a broad
# profile for Docker or Tailscale; maintain profiles separately and test them in
# complain mode first. The commands below verify the facility and preserve a
# clear audit record of its current state.
run systemctl enable --now apparmor
run aa-status

# Automatic security updates reduce time-to-patch for host packages.
run dpkg-reconfigure -f noninteractive unattended-upgrades

cat <<'SUMMARY'

Hardening complete (or previewed). Perform these validations before production:
  - ufw status verbose
  - tailscale status
  - tailscale serve status --json
  - ss -lntup | grep -E '(:8000|:443)'
  - auditctl -l
  - aa-status

Do not expose FastAPI directly to the public internet. Keep Tailscale Serve or
Services as the authenticated ingress, and keep any Tor onion administration
endpoint disabled until it has separate authentication and a security review.
SUMMARY
