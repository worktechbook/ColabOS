# ColabOS v1.1.8 - User Manual

## 1. Boot After VM Reclaim / Restart

1. Open your Colab notebook; mount Drive (`from google.colab import drive; drive.mount('/content/drive')`).
2. Run:
   ```python
   !bash /content/drive/MyDrive/ColabOS/boot
   ```
3. Wait ~0.4 s warm / ~20–40 s cold.
4. Verify:
   ```bash
   !svc doctor
   # Expected final line: ALL CHECKS PASSED (Healthy)
   ```
   If anything shows `[!!]`, run `!svc doctor --fix` to auto-heal.

   `svc doctor` on its own is **strictly read-only** — it will not extract, relink, or restart
   anything. Only `svc doctor --fix` makes changes. Doctor also verifies each app's content hash
   against the hash in its manifest, so a tampered install is reported.

5. Optional — run the engine self-test (read-only, ~10 s):
   ```bash
   !python3 /content/drive/MyDrive/ColabOS/engine/selftest.py
   # Expected: 145 passed, 0 failed
   ```

## 2. Use the Dev Tools

Installed versions (v1.0.0 bundle):
| Tool | Version |
|---|---|
| node | v24.19.0 |
| npm | 11.17.0 |
| bun | 1.3.14 |
| go | 1.22.6 |
| cargo | 1.97.1 |
| uv | 0.12.5 |
| rg (ripgrep) | 15.2.0 |
| fd, fzf, tree, jq | 8.3.1 / 0.72 / 2.0.2 / 1.6 |
| gh (GitHub CLI) | 2.103.3 |

Just run them normally — wrappers auto-snapshot:
```bash
npm update -g npm
cargo update
rustup update
```
When a wrapper detects an update/upgrade or a changed mtime, you'll see `[colabos] snapshot devtools`; it repacks the live install to a new deterministic tarball and prunes to keep the current artifact plus one prior revision.

In non-interactive shells (scripts, agent sessions), load the wrappers first:
```bash
source /etc/profile.d/colabos.sh
```

## 3. SSH Into the VM (Tailscale — permanent)

From any machine logged into the `example-tailnet.ts.net` tailnet (for example your Oracle VPS jump host or another trusted client with Tailscale running):
```powershell
ssh colabos-node
```
This uses `~/.ssh/colabos_ssh` to auth as `root` to `colabos-node.example-tailnet.ts.net` (`100.64.0.1`).

If you see `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED`:
1. Verify the new ed25519 host key ends `<YOUR_HOST_ED25519_KEY_SUFFIX>`.
2. Reset your local known_hosts:
   ```powershell
   ssh-keygen -R colabos-node.example-tailnet.ts.net
   ssh -o StrictHostKeyChecking=accept-new colabos-node "echo ok"
   ```

Quick check on the VM:
```
tailscale status
```
Expect the main peers you use operationally to show up here, especially `colabos-node` (this VM) and `gateway-vps` (your Oracle VPS gateway) when they are online.

## 4. Reverse SSH: VM → Oracle VPS gateway

When the `gateway-vps` peer is visible on the tailnet, the boot hook auto-writes a managed SSH config block like this:
```
Host gateway-vps
    HostName 100.64.0.2     (auto-discovered)
    User ubuntu
    IdentityFile /root/.ssh/colabos_ssh
    IdentitiesOnly yes
    ProxyCommand nc -X 5 -x 127.0.0.1:1055 %h %p
```
From the VM, run `ssh gateway-vps`. If the peer was offline during boot and the block is missing, rerun `bash /content/drive/MyDrive/ColabOS/apps/tailscale-ssh.sh` after `gateway-vps` is back online. To allow inbound access from the VM, add `colabos_ssh.pub` to the target account's `authorized_keys` on the Oracle VPS.

## 5. Inspecting & Managing Services

```bash
svc list                       # table of services / versions / hashes
svc status                     # health card for all services
svc status devtools            # one service: hash, size, persist sizes
svc doctor                     # pass/fail health
svc doctor --fix               # auto-heal broken symlinks, profile, bins, zstd
svc install <name>             # (re)install a service from its tarball
svc snapshot <name>            # manually repack (wrappers do this automatically)
svc logs <name>                # inspect known service log files
svc doc-table [--json]         # Markdown/JSON table from live manifests (also `list -m` / `status -m`)
```

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `Drive not at /content/drive/MyDrive/ColabOS` | Mount Drive first. `boot` now refuses to run when the Drive is unmounted or empty and prints exactly which precondition failed. |
| `zstd: command not found` | `apt-get update && apt-get install -y zstd` — or rerun `boot`, which installs it. |
| `doctor` reports `[!!] ... bin /usr/local/bin/...` | Run `svc doctor --fix` to recreate symlinks. |
| `doctor` reports `[!!] ... content hash` | The extracted install no longer matches its manifest hash — something modified it. Run `svc doctor --fix` to reinstall from the verified tarball. |
| `doctor` reports `[!!] ... artifact digest declared` | The manifest's `[artifact].sha256` is malformed. Recompute it with `sha256sum apps/<file>.tar.zst`. |
| `sftp` / `scp` fails with "Permission denied" or no subsystem | The SSH hook writes `Subsystem sftp`. Rerun `bash /content/drive/MyDrive/ColabOS/apps/tailscale-ssh.sh`. |
| SSH asks for a password over tailnet | Something went wrong — tailnet SSH is supposed to be key-only. Run `bash /content/drive/MyDrive/ColabOS/apps/tailscale-ssh.sh` to restore key-only sshd, then re-check. |
| Password auth works only while tunnel is up | Expected. That's by design; next ColabOS boot restores key-only. |
| `tailscale status` shows no peers | Wait a few seconds after boot; if still empty, check `/var/log/tailscaled.log` (or `svc logs tailscale-ssh`). |
| npm/cargo/gh updates don't survive restart | Check `svc doctor` for broken persist symlinks (`~/.cargo`, `~/.npm`, `~/.config/gh`); `--fix` recreates them. |
| Wrapper shows `[colabos] snapshot ...` every invocation | Something (e.g. an alias or another wrapper) is mutating the binary every shell start. Check for overlay filesystem weirdness; it's harmless but wastes time — run `svc snapshot <name>` manually once to clear it. |
| Newly added bin isn't wrapped | Add it to `bins = [...]` in the app's TOML, then run `svc install <name>` — wrappers are auto-generated on bootstrap. |

## 7. Adding a New Service

Ask the agent (or follow `docs/master/Agent.md` §6). The agent will create the tarball, TOML, lifecycle hook, and per-service docs, then `svc doctor --fix` must end with `ALL CHECKS PASSED`.

## 8. Where the Docs Are

- Root `README.md` — one-page overview, quick commands, changelog.
- `docs/master/README.md` — index.
- `docs/master/User_Manual.md` — this file.
- `docs/master/Architecture.md` — engine internals, TOML contract, security model.
- `docs/master/Agent.md` — autonomous-agent knowledge base (zero-context recovery); canonical home of the 7-step new-service flow.
- `docs/devtools/{README,Build_Log,User_Manual}.md`
- `docs/tailscale-ssh/{README,Build_Log,User_Manual}.md`
- `docs/oh-my-pi/{README,Build_Log,User_Manual}.md`

OMP runtime IPC is intentionally ephemeral through `~/.omp/run -> /run/omp-runtime`; sessions and configuration still persist under `~/.omp`. If interactive prediction or shared daemons fail, confirm `readlink ~/.omp/run` prints `/run/omp-runtime`.
