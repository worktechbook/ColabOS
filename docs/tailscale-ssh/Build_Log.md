# tailscale-ssh — Build Log (ColabOS service)

> Covers the ColabOS **service** only.
## V1.2.0 (2026-08-22, initial)
- Service v1.2.0 ships tailscale v1.102.2; artifact `tailscale-ssh-1.102.2-b5659c6aefdcadd2.tar.zst` (33 MiB); bins tailscale/tailscaled; lifecycle hook restored hostkeys, wrote key-only sshd_config, started tailscaled userspace, `tailscale serve --tcp 22`, reverse-SSH config. ALL CHECKS PASSED.
## V1.2.0 — v1.1.1 hardening (2026-08-26)
- Lifecycle hook is sentinel-aware: checks `/var/run/colabos-cf-bootstrap/` before touching sshd_config or SIGHUPing sshd, so external bootstrap sessions are not disrupted by mid-session `svc bootstrap`. Single canonical SSH identity. Graceful no-`gateway-vps`-peer fallback.
## V1.2.0 — 2026-08-30 doc/hook sync
- Implemented the documented sentinel-aware sshd guard in `apps/tailscale-ssh.sh`, normalized the managed reverse-SSH config flow for the Oracle VPS peer `gateway-vps`, and refreshed docs so the purpose and peer naming match the live environment.

## V1.2.1 (2026-09-29) — tailscale 1.102.2 → 1.102.4
- Downloaded `tailscale_1.102.4_amd64.tgz` from pkgs.tailscale.com, swapped both binaries via write-temp + `mv`, then `svc snapshot tailscale-ssh --version 1.2.1`.
- Artifact: `tailscale-ssh-1.2.1-7911f87eb4552014.tar.zst` (35.0 MiB); hash `7911f87eb4552014`.
- Daemon restarted (`pkill -x tailscaled` + lifecycle hook) so the running daemon is 1.102.4, not just the client.
- Mesh re-verified: 4 peers, `ssh gateway-vps` OK, ALL CHECKS PASSED.

## V1.2.1 - Re-hash (2026-10-31)
- **Hash:** `8bbd5ddcef573548` (artifact `tailscale-ssh-1.2.1-8bbd5ddcef573548.tar.zst`, 38 MiB, sha256 `7dd8ed0a99f1d921da77dac52d6dd9a26b99be45323efcf23742515fc1b4573f`).

## 2026-10-31
- Retained prior artifact: tailscale-ssh-1.2.2-98e7abe3b01240ac.tar.zst (37.0 MiB). — tailscale update
- Artifact re-packed and re-hashed after the Tailscale bump (38 MiB, sha256 `080e0d2b5b5784efab2eaa0b40ddabc9ccaa7422f9d1b44a9c236cb5f7972c49`).
- **Verification:** tailscaled restarted cleanly; `tailscale version` matched the shipped build; doctor green.
- Superseded by the v1.2.3 artifact recorded below.

## V1.2.3 (2026-11-09) — ColabOS v1.1.7 remediation pass
- **Version:** service 1.2.3; Tailscale bumped to 1.104.5.
- **Artifact (current):** `tailscale-ssh-1.2.3-1d324134bdbbe442.tar.zst` — 38,835,568 bytes (37 MiB).
- **Hash (deterministic):** `1d324134bdbbe442`; sha256 `93d4e6407b8b8cf467118045d066d4a0b23fe6dd7191d1a241ac9ef5f2f1f28d`.
- **Hook hardening (`apps/tailscale-ssh.sh`):**
  - Every sshd PID candidate (pidfile **and** `pgrep` fallback) is verified via `/proc/<pid>/cmdline`
    before `SIGHUP`; a stale pid file can no longer signal an unrelated process.
  - A failed Tailscale status lookup now **leaves the existing managed `gateway-vps` SSH config block
    unchanged** instead of replacing it with a placeholder.
  - Missing host-key `.pub` files are regenerated with `ssh-keygen -y` from the restored private key.
  - `iproute2` (`ss`) was added to the apt preflight, and apt install failures are now **fatal**.
  - A running `tailscaled` is reused only when its `--state`/`--socket` arguments match; otherwise it
    is restarted with the expected paths.
- **Single SSH identity:** the legacy `colab_ssh` private key and its fallback code were removed — only
  `colabos_ssh` ships.

## Post-v1.1.7 live remediation

- Added bounded peer discovery retry (`12 × 5 s`) for an initially empty Tailscale netmap.
- Status errors and persistent emptiness preserve the existing managed reverse-SSH block.
- Enforced mode 0600 on Drive-side identity/host private keys and `/root/.ssh/config`.
- Made package index and Tailscale hostname-setting failures fatal instead of silently continuing.
- Verified hook syntax, sentinel-safe runtime execution, tailnet port 22, and self-test contract.
