# ColabOS

> **One click should bring a disposable Google Colab machine back with your tools, services, and state already there.**

**Current engine:** v1.1.8 (8 commands + 145-check self-test, ~76 KiB).

ColabOS turns a temporary Google Colab VM (CPU+RAM, wiped on reclaim) into a persistent service platform that behaves more like your local machine after login. It uses mounted Google Drive as durable disk, restores CLI tools, long-running servers, and cloud-connected app state, and wires the VM onto your Tailscale mesh so everything is ready to use after a single boot command.

---

## ⚡ 1-Click Bootstrap

```python
!bash /content/drive/MyDrive/ColabOS/boot
```

| Metric | Value |
|---|---|
| Warm boot (fast-path, already extracted) | **~0.4 s** (measured 0.39–0.49 s wall, ~0.08 s engine fast-path, 3 apps) |
| Cold boot (new VM, ~785 MiB extracted) | ~20–40 s |
| Full `svc doctor` (hashes every store tree) | ~15–40 s |
| Health command | `svc doctor` |
| Health command (auto-fix) | `svc doctor --fix` |
| Current version | **v1.1.8** |

---

## 🛠️ Active Services

| Service | Type | Access | Details |
|---|---|---|---|
| **tailscale-ssh** | `server` | `ssh colabos-node` on the Tailscale mesh | Permanent key-only SSH at `100.64.0.1` (`colabos-node.example-tailnet.ts.net`), Tailscale v1.104.5, SOCKS5 on `127.0.0.1:1055`, managed reverse-SSH config auto-written for the Oracle VPS peer `gateway-vps` when that peer is visible on the tailnet. |
| **devtools** | `tool` | 20 commands on `PATH` | Node v24.19.0, npm 11.17.0, Bun 1.3.14, Go 1.22.6, Rust cargo 1.97.1 / rustup, uv 0.12.5, ripgrep, fd, jq, fzf, tree, gh, pnpm, yarn, bunx, uvx, gofmt, rustc, npx. Auto-snapshot on update. |
| **oh-my-pi** | `tool` | `omp` on `PATH` | omp v19.0.1 agent CLI (TUI/-p/RPC, NVIDIA provider). State + auth persist in `home/oh-my-pi/omp/`. |



---

## 🧭 Architecture in one line

> **VM is CPU, Drive is Disk, Hash is Truth, Overlay is View, Mesh is Address.**

- **VM = CPU** — the overlayFS root is wiped every reclaim.
- **Drive = Disk** — `/content/drive/MyDrive/ColabOS` on FUSE `fuse.drive` holds immutable tar.zst archives, state, keys, and docs.
- **Hash = Truth** — every artifact is named `<name>-<ver>-<16-char-sha256>.tar.zst` (deterministic, `tar --sort=name`); doctor verifies the live install matches the hash in TOML.
- **Overlay = View** — at boot, archives are extracted once to `/opt/colabos/store/<name>-<ver>-<hash>` and symlinked into `/opt/colabos/<name>`; binaries symlink into `/usr/local/bin`; state directories symlink from `$BASE/home/<svc>/` into `/root`, `/var/lib`, `/etc`.
- **Mesh = Address** — Tailscale runs in userspace mode (Colab lacks `/dev/net/tun`) with a SOCKS5 proxy on 127.0.0.1:1055, giving the VM a stable identity at `100.64.0.1`.

---

## 📂 Layout

```
/content/drive/MyDrive/ColabOS/
├── boot              2.8 KB    bash entrypoint (mount-check + toolchain-check + svc bootstrap)
├── engine/svc        76 KB    Python 3 engine (8 commands, self-healing)
├── engine/selftest.py 43 KB   engine regression suite (145 checks, read-only)
├── apps/                      content-addressed tar.zst + TOML manifests + lifecycle .sh
│   ├── devtools-1.0.0-a92aed243b76f7dc.tar.zst      (current, 370.1 MiB)
│   ├── devtools.toml
│   ├── devtools.sh             Rust toolchain -> persistent rustup home hook
│   ├── tailscale-ssh-1.2.3-1d324134bdbbe442.tar.zst (37 MiB, tailscale v1.104.5)
│   ├── tailscale-ssh.toml
│   └── tailscale-ssh.sh     sentinel-aware server lifecycle hook
│   ├── oh-my-pi-19.0.1-f93076d1a2cb38dc.tar.zst (current, 164.6 MiB)
│   ├── oh-my-pi-19.0.0-50bcf07c7b4b65f1.tar.zst (prior, 164.6 MiB)
│   ├── oh-my-pi.toml
│   └── oh-my-pi.sh             runtime-dir refresh + key wiring hook
├── home/                      persistent state (symlinked into VM)
│   ├── devtools/{cargo,npm,gh,rustup}/
│   ├── tailscale-ssh/{keys,ssh-hostkeys,tailscale/}
│   └── oh-my-pi/{omp/,nvidia.key,firecrawl.key}
└── docs/
    ├── master/{README,Architecture,Agent,User_Manual}.md
    ├── devtools/{README,Build_Log,User_Manual}.md
    ├── tailscale-ssh/{README,Build_Log,User_Manual}.md
    └── oh-my-pi/{README,Build_Log,User_Manual}.md
```

FUSE performance note: small writes on Drive are ~25 ms vs ~1 ms on tmpfs (~25× slower), so binaries always execute from `/opt/colabos` after extraction; Drive only stores archives and state.

---

## ⚙️ Engine (`svc`) — 8 commands

```bash
svc bootstrap              # flock + parallel install of all apps + write profile
svc list                   # table of services / versions / hashes / install state
svc status    [name]       # detailed health card: hash verification, sizes, health, persist
svc install   <name>       # extract + link bins + persist symlinks + run server hook
svc install   <name> --force  # re-extract the artifact even if the store dir exists
svc snapshot  <name>       # repack live install, reconcile the install, prune to current + one prior
svc doctor   [--fix]       # verify Drive/zstd/symlinks/bins/persist/server-health; --fix auto-heals
svc logs     <name>       # inspect service log files declared/known for an app
svc doc-table [--json]    # emit Markdown/JSON state table from live manifests (also `list`/`status` -m)
```

All commands are safe to re-run. A `flock` on `/run/colabos/colabos.lock` prevents concurrent boots, installs, snapshots, and `doctor --fix`.

### Shell wrappers (auto-generated, not hand-written)

`svc bootstrap` writes `/etc/profile.d/colabos.sh` (generated from TOML `bins[]`). Each wrapped binary dispatches through one generic `_colabos_wrap` function that records a sub-second mtime, runs the command, and triggers `svc snapshot <app>` only when:
1. argv[1] is exactly one of `update`, `upgrade`, or `self-update` **and** no `--help/--version/--dry-run/--check` flag is present, **and** the command succeeded; or
2. the binary's mtime changed after the command (catches self-updaters like `rustup`).

`install` is deliberately **not** an update verb — `npm install <pkg>` is an ordinary package install and must not repack the whole bundle.

Wrapper snapshots are serialized via `/run/colabos/colabos_snapshot.lock` so concurrent updates don't race.

### Snapshot

- `svc snapshot` packs the live install deterministically (`tar --sort=name | zstd -6 -T0`), writes the archive atomically, and then **reconciles the live installation**: the store directory is renamed to the new content-addressed stem, `/opt/colabos/<name>` is repointed, `/usr/local/bin` links are relinked, and the lifecycle hook is re-run. The manifest and the installation never diverge.
- Old artifacts are pruned to exactly the current one plus one prior, scoped to this app only.

### Doctor self-healing (`--fix`)

Without `--fix`, doctor is **strictly read-only** — it never extracts, relinks, or restarts anything. With `--fix` it takes the engine lock and can recreate missing `/usr/local/bin/svc`, regenerate the profile, relink missing bin symlinks (using a depth-3 walk to find binaries in nested bin dirs), create missing persist directories, install `zstd` if absent, and **re-extract a corrupted store tree** so a tampered install is actually healed.

A repair that fails is reported as `[ERR]` — never as a successful `[fix]`.

Doctor also verifies each app's **content hash** (the extracted tree must match the hash in its store directory name) and each manifest's declared `[artifact].sha256` format.

### Engine self-test

```bash
python3 /content/drive/MyDrive/ColabOS/engine/selftest.py
# 145 passed, 0 failed
```

Read-only regression suite covering TOML parsing, dependency ordering (including cycles and missing deps), content hashing with exclusions, artifact digest tamper detection, health-probe timeouts, doctor read-only behaviour, truthful repair reporting, atomic manifest writes, strict dependency validation, wrapper generation and shell escaping, app-scoped artifact pruning, forced reinstall, deterministic binary resolution, manifest schema + digest integrity, the CLI surface, and bash syntax of every lifecycle hook.

---

## 🔐 SSH & Network

**Permanent path (Tailscale mesh, key-only):**
- sshd config: `PasswordAuthentication no`, `PermitRootLogin prohibit-password`, `PubkeyAuthentication yes`.
- sshd config includes `Subsystem sftp /usr/lib/openssh/sftp-server` and places `Include /etc/ssh/sshd_config.d/*.conf` **last** (OpenSSH uses the first value for most keywords, so hardened base settings come first and drop-ins cannot silently re-enable password auth).
- Single canonical SSH identity: `colabos_ssh` (ed25519). Pubkey is the sole entry in `authorized_keys` and is also used for outbound reverse-SSH to the Oracle VPS peer `gateway-vps` via the SOCKS5 proxy. The legacy `colab_ssh` key and its fallback code were removed, so there is genuinely exactly one identity.
- Host keys (ed25519 + RSA) live in `home/tailscale-ssh/ssh-hostkeys/` and are copied (not symlinked) to `/etc/ssh/` every boot. Ed25519 host pubkey ends `<YOUR_HOST_ED25519_KEY_SUFFIX>`. Missing `.pub` files are regenerated with `ssh-keygen -y` from the private key.
- `tailscale serve --bg --tcp 22 tcp://127.0.0.1:22` forwards tailnet port 22 to the local sshd.
- The hook validates the generated config with `sshd -t` before reloading, verifies sshd is actually listening on :22, restarts `tailscaled` when the on-disk binary changed or when a running daemon's `--state`/`--socket` arguments do not match the configured paths, and **fails loudly** if Tailscale is not authenticated or the serve mapping cannot be applied.
- Before signalling sshd, the hook verifies the candidate PID via `/proc/<pid>/exe` (and `PPid: 1` in `/proc/<pid>/status` for the `pgrep` fallback) so a recycled PID is never sent a SIGHUP.
- If the Tailscale status lookup fails, the hook **leaves the existing managed `gateway-vps` block in `~/.ssh/config` untouched** instead of replacing it with a placeholder; a transient status failure must not destroy a working reverse-SSH config.

---

## 🚦 Quick Reference

```bash
# boot (warm)
bash /content/drive/MyDrive/ColabOS/boot
# check health
svc doctor
# auto-heal
svc doctor --fix
# see what's installed
svc list
svc status
svc logs tailscale-ssh
# use tools
node --version   # v24.19.0
go version       # go1.22.6
cargo --version  # 1.97.1
rg --version
omp --version       # 19.0.1
# reverse-SSH to the Oracle VPS gateway (managed block in `~/.ssh/config`)
ssh gateway-vps
```

---

## 📚 Docs

- **Human start here:** `docs/master/User_Manual.md`
- **Architecture deep-dive:** `docs/master/Architecture.md`
- **Zero-context agent reference (canonical):** `docs/master/Agent.md`
- **Docs index:** `docs/master/README.md`
- **Per-service:** `docs/devtools/{README,Build_Log,User_Manual}.md`, `docs/tailscale-ssh/{README,Build_Log,User_Manual}.md`, `docs/oh-my-pi/{README,Build_Log,User_Manual}.md`

---

## 📜 Changelog

- **Live remediation — OMP and consistency:** OMP updated to **18.18.6** (`340eb101c8cef6a7`, SHA-256 `c072df1e…f3df`); current-plus-prior retention restored with 18.18.3; SSH peer discovery now retries an initially empty Tailscale netmap; self-test is **112/112**; leaked key/token literals were scrubbed from persisted audit transcripts, the stale broker token was rotated by removing dead runtime state, and duplicate root-level certificate files were removed after byte-for-byte verification against the canonical Tailscale copies.

- **2026-11-03** — **opencode removed completely** (app, tarballs, `home/opencode/` state, `docs/opencode/`, live VM install). Reason: persisted `opencode.db` corruption broke the models.dev plugin after cold restart; omp covers the agent use case.
- **tailscale-ssh** (2026-11-03) — updated v1.2.2 → v1.2.3 (tailscale v1.104.4 → **v1.104.5**, hash `1d324134bdbbe442`, 37 MiB); daemon restarted, serve :22 verified.
- **oh-my-pi** (2026-11-03) — updated v18.14.1 → **v18.16.0** (`5ba96a1be717c961`, 150 MiB).
- **v1.0.0** (2026-08-22) — initial release: drive-backed boot, tar.zst artifacts, Tailscale SSH, devtools bundle.
- **v1.1.3** (2026-08-26) — "Agent-Proof" hardening: `svc status` / `svc doctor --fix`; deterministic tar hashes; auto-generated shell wrappers; sentinel-based external-session protection for sshd lifecycle; single canonical SSH identity; cleaned stale tailscale auth-url and orphan tarballs; all docs cover ColabOS services only.
- **v1.1.4** — rollback removed (`svc rollback` gone, snapshot keeps current plus one prior tarball); `devtools.toml` strict-TOML fix; wrapper auto-snapshot fix.
- **oh-my-pi** (2026-09-06) — new tool app v18.1.11, updated 2026-09-09 to v18.11.3 (`6a951efffaff46f2`, 117 MiB prebuilt binary, user-configured provider; native `omp update` + wrapper auto-snapshot verified).
- **v1.1.5** — runtime smoke health for tools; current + prior artifact retention; pnpm/yarn launcher and documentation drift repairs.
- **oh-my-pi** (2026-10-31) — updated v18.13.3 → v18.14.1 (`7b45d1be2b1bb25f`, 151 MiB).
- **devtools** (2026-10-31) — re-hashed to `eb5777638b4b7eaa` (567 MiB).
- **tailscale-ssh** (2026-10-31) — updated v1.2.1 → v1.2.2 (tailscale v1.102.4 → v1.104.4, hash `98e7abe3b01240ac`, 38 MiB).
- **oh-my-pi** (2026-10-18) — updated v18.11.3 → v18.12.1 (`51077e745596fc4b`, 136.7 MiB) via `omp update`; verified live after the bump.
- **Native updaters are not artifact-aware** — `omp update` rewrites the extracted store binary. It does not update the Drive artifact, so it leaves ColabOS pointing at the old version until you re-stage, repackage, bump the TOML, and `svc install`.
- **v1.1.6** (2026-10-25) — correctness + durability pass over the whole system:
  - *Engine:* `svc doctor` is now strictly read-only without `--fix` (it previously ran `install_app` — extract + lifecycle hook — on a plain doctor run); bootstrap installs in dependency **levels** so a dependent app's hook cannot start before its dependency's hook returned; optional `[artifact].sha256` is verified before extraction (fails closed) and the extracted tree is re-hashed against the manifest hash; all health probes have a bounded timeout; the auto-snapshot wrapper resolves the binary with `type -P` (inside the wrapper function `command -v` returned the function name, so the mtime check could never fire); `svc snapshot` takes the engine lock; persist rescue backups (`.bak-<ts>`) are pruned to the newest per target; `svc --version` added; doctor now verifies each app's **content hash**.
  - *Boot:* preconditions are now verified — Drive is actually mounted and non-empty, the ColabOS tree and manifests are present, `python3` is available, `zstd` is installed — each with a specific error message instead of a generic failure.
  - *System:* `/usr/local/bin` was owned by `ubuntu:ubuntu`, letting a non-root user replace binaries that root executes — now `root:root`.
  - *Tests:* new `engine/selftest.py` — 64 read-only regression checks covering TOML parsing, dependency ordering, hashing, digest tamper detection, probe timeouts, doctor read-only behaviour, manifest integrity, CLI surface, and hook syntax.
- **v1.1.7** (2026-11-09) — second correctness + durability pass; the focus was *engine truthfulness* (never report success for work that did not happen) and *state hygiene*.
  - *Engine — truthfulness:* `doctor --fix` now reports a failed repair as `[ERR]` instead of `[fix]`; a declared binary that cannot be resolved now **fails** the install instead of being silently skipped; a missing dependency or a dependency cycle is now a **hard error** at bootstrap instead of a silent ordering downgrade; binaries are chmod'ed to 0755 *before* hashing so an archived 0644 mode no longer produces a false hash mismatch; persist rescue backups use unique names (timestamp + pid) so two rescues in the same second cannot nest.
  - *Engine — durability:* `svc snapshot` now **reconciles the live install** (store dir renamed to the new hash stem, `/opt/colabos/<name>` repointed, `/usr/local/bin` links relinked, lifecycle hook re-run), so the manifest and the installation can no longer diverge; `doctor --fix` re-extracts a corrupted store tree instead of only reporting it; `doctor --fix` takes the engine lock so it cannot race a concurrent bootstrap/install/snapshot; manifest, profile and MOTD writes are atomic (temp file + rename); every health probe is bounded by 20 s, including in `install` and `status`; `svc status` persist sizing is bounded (it previously took >600 s walking the Drive tree); `svc install <name> --force` re-extracts even when the store dir exists.
  - *Engine — wrappers:* `install` is no longer an update verb, so `npm install <pkg>` no longer triggers a 567 MB snapshot; mtime tracking is sub-second (`stat -c %.9Y`); manifest env values are shell-quoted before being written into the profile.
  - *Boot:* a real Drive FUSE mount is now **required** — the old "not a mountpoint but non-empty, continue" fallback could silently treat an unmounted directory as the durable disk; boot also requires root.
  - *SSH hook:* every sshd PID candidate (pidfile **and** pgrep fallback) is verified via `/proc/<pid>/cmdline` before SIGHUP, so a recycled PID is never signalled; a failed Tailscale status lookup now **leaves** the existing managed `gateway-vps` block unchanged instead of replacing it with a placeholder; missing host-key `.pub` files are regenerated via `ssh-keygen -y`; `iproute2` (for `ss`) was added to the apt preflight and apt failures are now fatal; a running `tailscaled` is reused only if its `--state`/`--socket` arguments match, otherwise it is restarted.
  - *OMP hook:* `/etc/profile.d/omp-web.sh` is written atomically (temp + `mv`, mode 0600 root:root); Drive key files are chmod 0600; `$HOME_OMP/omp/run` is mode 0700; the hook now exits 1 if `omp` is missing or `omp --version` fails, instead of silently reporting success.
  - *devtools:* `RUSTUP_HOME` moved from inside the artifact to the persistent Drive home; the toolchain stays in the artifact and is linked into the persistent rustup home by the new `apps/devtools.sh` hook, so rustup's mutable state (settings, downloads, update hashes) no longer mutates the artifact; the 279 MB dead `cargo/` directory (15 identical rustup proxy copies plus a stale `cargo/env` pointing at `/tmp/stage_devtools`) was removed; artifact is now 370.1 MiB (`a92aed243b76f7dc`).
  - *State hygiene:* removed the probe files, `engine/__pycache__`, the legacy `colab_ssh` private key **and** its fallback code (so the documented single-identity rule is now true), stale session directories, stale provider-inflight entries, npm debug logs, zero-byte rotated logs, two stale Tailscale `_serve` entries (an alternate hostname and an HTTPS 443→20133 mapping), three stale Tailscale profile caches, the stale `colabos-node.legacy-tailnet.ts.net` certificate, and an external-domain file-share scope.
  - *Tests:* `engine/selftest.py` grew from 64 to **96** read-only regression checks, adding coverage for truthful repair reporting, atomic manifest writes, strict dependency validation, wrapper generation and shell escaping, app-scoped artifact pruning, forced reinstall, and deterministic binary resolution.

- **Maintenance readiness pass:** OMP updated through its verified native updater/snapshot path to **18.22.0** (`870c2f462077a738`, SHA-256 `12dc5bc1…a7a`). OMP runtime IPC now uses owner-only local `/run/omp-runtime` through the persisted `~/.omp/run` symlink because Drive FUSE cannot bind Unix sockets; persisted dead IPC residue and three stale Chrome singleton symlinks were removed. Devtools version documentation was corrected to live artifact truth.
