# tailscale-ssh v1.2.3 — ColabOS Service (Tailnet SSH)

> This directory documents the **ColabOS `tailscale-ssh` service** (`type = server`, engine v1.1.8)
> — permanent Tailscale-mesh SSH that boots with `svc bootstrap` (key-only,
> tailnet-only access via SOCKS5 on `127.0.0.1:1055`).
>
> **Covers ColabOS internals only.** External / pre-boot access helpers are
> out of scope for ColabOS documentation.

## What this ColabOS service does
- Ships Tailscale `tailscale`/`tailscaled` v1.104.5 (`apps/tailscale-ssh-1.2.3-1d324134bdbbe442.tar.zst`, 37 MiB, sha256 `93d4e6407b8b8cf467118045d066d4a0b23fe6dd7191d1a241ac9ef5f2f1f28d`; prior v1.2.2: `tailscale-ssh-1.2.2-98e7abe3b01240ac.tar.zst`).
- On every `svc bootstrap` / `bash .../ColabOS/boot`:
  1. Copies the canonical `colabos_ssh` keypair into `/root/.ssh`; ensures `authorized_keys` contains only that pubkey.
  2. Installs `netcat-openbsd` for SOCKS5 proxying and `iproute2` (`ss`) for port checks; apt install failures are **fatal**.
  3. Restores stable SSH hostkeys from `home/tailscale-ssh/ssh-hostkeys/`; missing `.pub` files are regenerated with `ssh-keygen -y`.
  4. Writes key-only `/etc/ssh/sshd_config` and reloads sshd **unless** `/var/run/colabos-cf-bootstrap/` exists (sentinel that signals an external bootstrap session is active and sshd must not be reconfigured mid-session).
  5. Starts `tailscaled --tun=userspace-networking --socks5-server=127.0.0.1:1055` against Drive-persisted state; a running `tailscaled` is reused only when its `--state`/`--socket` arguments match, otherwise it is restarted.
  6. Sets hostname `colabos-node`, runs `tailscale serve --bg --tcp 22 tcp://127.0.0.1:22` (tailnet-only, no funnel).
  7. Auto-discovers the Oracle VPS peer (`gateway-vps`) via `tailscale status --json` and writes a managed `/root/.ssh/config` block so `ssh gateway-vps` works through the local SOCKS5 proxy. If the peer is not currently visible or status lookup fails, it leaves the existing managed SSH block unchanged and continues gracefully.

## Hook hardening (v1.1.7)

- **sshd PID verification:** every sshd PID candidate (pidfile *and* `pgrep` fallback) is verified through
  `/proc/<pid>/exe` (and `PPid: 1`) before `SIGHUP` is sent — a stale pid file can no longer signal an unrelated process.
- **gateway-vps block preserved:** if the Tailscale status lookup fails, the existing managed `gateway-vps`
  SSH config block is left **unchanged** (it used to be replaced by a placeholder).
- **Host-key `.pub` regeneration:** missing `ssh_host_*_key.pub` files are regenerated with `ssh-keygen -y`
  from the restored private key instead of being left absent.
- **Preflight:** `iproute2` (`ss`) was added to the apt preflight, and apt install failures are now fatal
  rather than being swallowed.
- **tailscaled reuse is conditional:** a running `tailscaled` is reused only if its `--state`/`--socket`
  arguments match the expected paths; otherwise it is restarted with the correct arguments.
- **Single SSH identity:** exactly ONE identity ships — `colabos_ssh`. The legacy `colab_ssh` private
  key (and its fallback path in the hook) was removed.

## Persist
- `home/tailscale-ssh/tailscale/` → `/var/lib/tailscale`.
- `home/tailscale-ssh/keys/` → `/root/.ssh/keys_backup`.
- `home/tailscale-ssh/ssh-hostkeys/` → copied into `/etc/ssh/`.

## Bins: `tailscale`, `tailscaled`
## Env: `TAILSCALE_HOSTNAME=colabos-node` → 100.64.0.1 / colabos-node.example-tailnet.ts.net
## Security: key-only by default. When an external bootstrap session is active (sentinel `/var/run/colabos-cf-bootstrap/` exists), sshd is left untouched so the external session is not disrupted.
## Connecting (permanent): from any machine on example-tailnet.ts.net → `ssh colabos-node`
## Reverse-SSH (from the VM): `ssh gateway-vps` once that peer is online and the managed config block has been written
## Build Log: Build_Log.md · Tailnet User Manual: User_Manual.md

## Peer-discovery retry and key-mode enforcement

The managed `gateway-vps` lookup retries an empty Tailscale peer map 12 times at five-second intervals. A failed or persistently empty status read leaves the existing managed SSH block byte-for-byte intact. Drive-side identity and host private keys are enforced at 0600, and `/root/.ssh/config` is mode 0600.
