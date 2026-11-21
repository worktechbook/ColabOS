# tailscale-ssh v1.2.3 — User Manual (ColabOS service)

> Covers the **permanent Tailnet SSH** path (key-only, tailnet-only). For
> tailnet access, run `bash boot` and then `ssh colabos-node` once the
> Tailscale mesh is up.
>
> **Covers ColabOS internals only.** External / pre-boot access helpers are
> out of scope for ColabOS documentation.

## Artifact

Current: `tailscale-ssh-1.2.3-1d324134bdbbe442.tar.zst` (37 MiB) in `/content/drive/MyDrive/ColabOS/apps/`
SHA-256: `93d4e6407b8b8cf467118045d066d4a0b23fe6dd7191d1a241ac9ef5f2f1f28d`
Tailscale binaries: `tailscale` / `tailscaled` v1.104.5

## Connecting (Tailscale mesh)
```powershell
ssh colabos-node
```
Stable ed25519 hostkey: `ssh-ed25519 <YOUR_HOST_ED25519_PUBLIC_KEY>`
## Reverse SSH: VM → Oracle VPS gateway via SOCKS5 proxy: `ssh gateway-vps`
## Check: `tailscale status`
## SSH identities
Exactly one identity ships with this service: `colabos_ssh`. The legacy `colab_ssh` key was
removed, so `ssh colabos-node` and `ssh gateway-vps` both authenticate with `colabos_ssh`
(`IdentityFile /root/.ssh/colabos_ssh`, `IdentitiesOnly yes`).
## Troubleshooting:
- Password auth rejected on tailnet is expected (key-only). Run `bash /content/drive/MyDrive/ColabOS/apps/tailscale-ssh.sh` to re-apply.
- tailscaled failures → check `/var/log/tailscaled.log` (or `svc logs tailscale-ssh`); `--tun=userspace-networking` is mandatory.
- Reverse-SSH failures → confirm `gateway-vps` is online, rerun `bash /content/drive/MyDrive/ColabOS/apps/tailscale-ssh.sh` if the managed `~/.ssh/config` block is missing, make sure `colabos_ssh.pub` is in the target account's `authorized_keys`, and verify `nc` is installed.
  If the Tailscale status lookup itself fails, the hook now leaves the existing managed `gateway-vps` block untouched instead of replacing it with a placeholder.
- Host-key changed → `ssh-keygen -R colabos-node.example-tailnet.ts.net` after verifying the new key matches `<HOST_KEY_SUFFIX>`.
- Missing host-key `.pub` files are regenerated from the restored private key with `ssh-keygen -y` on the next hook run.
- `ss` missing → the hook installs `iproute2` in its apt preflight; apt install failures are fatal, so a failed install surfaces as a hook error instead of a silent misconfiguration.
- sshd did not reload → the hook verifies each candidate sshd PID through `/proc/<pid>/exe` (and `PPid: 1`) before sending `SIGHUP`; a stale pid file is ignored and the real master is located instead.

## Empty peer map after daemon start

A newly started daemon can briefly report no peers. The hook now waits up to 60 seconds before giving up, and giving up preserves the previous managed reverse-SSH block. Rerun the hook after the mesh is available; do not delete a working block merely because the first status read is empty.
