# ColabOS Architecture (v1.1.8)

> For boot/use instructions see `docs/master/User_Manual.md`. For agent rules and the 7-step new-service flow see `docs/master/Agent.md` §6.

## 1. Philosophy

ColabOS turns a free Google Colab VM into a persistent service environment. The author's daily laptop has only 8 GB RAM; Colab gives a bigger VM plus 108 GB of mounted Google Drive, but the VM root is wiped on every reclaim. ColabOS bridges the gap by restoring the tools, servers, and cloud-connected state you expect to already be there after login.

The five axioms:
1. **VM is CPU.** `/` is an overlay FS wiped on reclaim.
2. **Drive is Disk.** `/content/drive/MyDrive/ColabOS` (FUSE `fuse.drive`) is the source of truth: immutable archives + mutable state + keys + docs.
3. **Hash is Truth.** Artifacts are named `<name>-<ver>-<16-char-sha256>.tar.zst`. Hashes are deterministic (`tar --sort=name`). Doctor verifies the live install's hash matches TOML.
4. **Overlay is View.** At boot, archives extract to `/opt/colabos/store/<name>-<ver>-<hash>`; live view is a symlink `/opt/colabos/<name>`; binaries symlink into `/usr/local/bin`; state symlinks from `$BASE/home/<svc>/...` into `/root`, `/var/lib`, `/etc`.
5. **Mesh is Address.** Tailscale runs in `--tun=userspace-networking` mode (no `/dev/net/tun` in Colab) with SOCKS5 on `127.0.0.1:1055`. Stable IP `100.64.0.1`, MagicDNS `colabos-node.example-tailnet.ts.net`.

Verified performance:
- Drive FUSE small write ~25 ms vs tmpfs ~1 ms (~25×). Binaries execute from `/opt/colabos` (ext4 overlay) to avoid the penalty.
- FUSE supports `chmod +x`; `boot` and `engine/svc` run directly off Drive (they're small).
- `zstd` is installed on demand by `boot` via `apt-get install -y zstd`.
- Warm boot ~0.4 s wall (measured 0.39–0.49 s, 3 apps); the engine's own fast-path phase is ~0.08 s. Cold boot ~20–40 s (~571.7 MiB to extract + server start).
- A full `svc doctor` takes ~31 s because it hashes every store tree to verify content hashes. That is deliberate and off the boot hot path — the bootstrap fast path uses a shallow check.

## 2. Layout

```
/content/drive/MyDrive/ColabOS/
├── boot                              # 2.5 KB bash entrypoint (precondition checks)
├── engine/
│   ├── svc                           # ~76 KiB, Python 3 CLI (8 commands: bootstrap, doctor, list, status, install, snapshot, logs, doc-table)
│   └── selftest.py                   # read-only regression suite (145 checks)
├── apps/
│   ├── <name>.toml                   # manifest
│   ├── <name>-<ver>-<hash>.tar.zst   # immutable artifacts (current + one prior)
│   └── <name>.sh                     # lifecycle hook (any type; servers use it for daemons)
├── home/<svc>/...                    # persistent state, symlinked into VM
└── docs/
    ├── master/{README,Architecture,Agent,User_Manual}.md
    └── <svc>/{README,Build_Log,User_Manual}.md
```

Out-of-band (live VM paths, not inside ColabOS/ — all regenerated or repointed every boot):
- `/opt/colabos/store/<name>-<ver>-<hash>/` — extracted artifacts; `/opt/colabos/<name>` — live symlinks
- `/usr/local/bin/<bin>` — bin symlinks; `/usr/local/bin/svc` — engine shim
- `/etc/profile.d/colabos.sh` — generated wrappers; `/etc/profile.d/colabos-motd.sh` — login banner
- `/run/colabos/colabos.lock` — bootstrap lock; `/run/colabos/colabos_snapshot.lock` — snapshot serialization
- `/etc/ssh/sshd_config`, `/root/.ssh/config` (managed block), `/etc/ssh/ssh_host_*` — written by ssh hook
- `/content/drive/MyDrive/Colab Notebooks/` — regular notebooks, out of scope

Constants (in `engine/svc`):
```python
BASE      = "/content/drive/MyDrive/ColabOS"
OPT       = "/opt/colabos"
STORE_OPT = "/opt/colabos/store"
BIN_DIR   = "/usr/local/bin"
PROFILE_D = "/etc/profile.d/colabos.sh"
MOTD_D    = "/etc/profile.d/colabos-motd.sh"
RUN_DIR   = "/run/colabos"
LOCK_FILE = "/run/colabos/colabos.lock"
WRAP_SNAPSHOT_LOCK = "/run/colabos/colabos_snapshot.lock"
```

## 3. Engine (`engine/svc`)

Subcommands: `bootstrap`, `list [-m]`, `status [name] [-m]`, `install <name> [--force]`, `snapshot <name> [--version V]`, `doctor [--fix]`, `logs <name>`, `doc-table [--json]`.

### bootstrap
1. Acquire exclusive `flock` on `/run/colabos/colabos.lock` (non-blocking first, prints "waiting for lock" then blocks).
2. Ensure `/usr/local/bin/svc -> engine/svc`.
3. Discover apps by globbing `apps/*.toml`.
4. Install all apps in **dependency levels** (see §6a). Apps within one level install in parallel (ThreadPoolExecutor, 3 workers); the next level starts only after every app in the current level installed *and* its lifecycle hook returned successfully. A missing dependency or a dependency cycle is a **hard error** — bootstrap aborts instead of silently downgrading the ordering guarantee.
5. Write `/etc/profile.d/colabos.sh` from TOML data — **generated**, not hand-written (atomic temp file + rename).
6. Server lifecycle hooks already ran inside `install`. Prints warm/cold boot time.

**Fast path:** if a **shallow** `svc doctor` passes on entry, the whole reinstall/relink pass is skipped (~0.08 s). The shallow check skips the two expensive things: the content-hash comparison (which hashes every store tree) and the full manifest health commands (which run every tool binary's `--version` and, for servers, reach the public URL). Instead it does a cheap TCP connect to each server's exposed port, so a dead server is still detected and triggers the full bootstrap path. Because doctor is now strictly read-only without `--fix`, this check can no longer restart a service as a side effect.

### install <name> [--force]
1. Parse TOML. `load_toml` uses stdlib `tomllib` (Python 3.11+) with a hand-rolled fallback parser that handles quoted keys.
2. Locate artifact file. If the manifest declares `[artifact].sha256`, the tarball's sha256 is verified **before** extraction — a mismatch aborts the install (fail closed).
3. If the store directory doesn't exist — or `--force` was given — extract `tar -I 'zstd -T0' -xf` into `<store>.tmp`, atomic rename, then re-hash the extracted tree and compare it with the hash in the store directory name. `--force` re-extracts **even when the store dir already exists**, which is the repair path for a corrupted or tampered tree. Print elapsed time and MiB.
4. Re-point live symlink `/opt/colabos/<name>` to the store directory.
5. For each bin in `[artifact].bins`, use `find_bin()` which walks `*/bin/<b>` (depths 0–3, sorted deterministically, e.g. `bin/<b>` or `lib/node/bin/npm`) (e.g. `lib/node/bin/npm`), chmod 0755, symlink to `/usr/local/bin/<b>`. A declared binary that cannot be resolved **fails the install** (it is not silently skipped); candidate resolution is deterministic (sorted).
6. For each `[persist] src_rel = dst_abs`, `mkdir -p` source, rescue any real destination to `dst.bak-<timestamp>-<pid>` (unique names, so two rescues in the same second cannot nest; keeping only the newest rescue copy per target), then symlink `dst_abs -> $BASE/src_rel`.
7. For servers, invoke `apps/<name>.sh` (preferred) or use a generic starter; expose port via `tailscale serve --bg --tcp <port>` (mode=tailnet) or `tailscale funnel --bg <port>` (mode=funnel).
8. Every manifest health probe is bounded (20 s), including the probes run during `install`.

**chmod before hash:** declared binaries are chmod'ed to 0755 **before** the extracted tree is hashed. The content hash covers tar metadata (including the file mode), so an archived 0644 mode would otherwise cause a false hash mismatch on the next doctor run.

### snapshot <name> [--version V]
- Hash live directory with `tar --sort=name -cf - -C <real> . | sha256sum | cut -c1-16` (deterministic).
- Pack with `zstd -6 -T0` to `apps/<name>-<ver>-<newhash>.tar.zst`, print packed size & elapsed time.
- Rewrite `[artifact].file` in `<name>.toml` with the minimal TOML writer. Manifest writes are **atomic** (temp file + rename).
- **Reconciles the live install**: the store directory is renamed to the new content-addressed stem, `/opt/colabos/<name>` is repointed, the `/usr/local/bin` binaries are relinked, and the lifecycle hook is re-run. The manifest and the installation never diverge after a snapshot.
- Prune app-scoped to **exactly the current artifact plus one prior artifact**.
- Takes the engine lock (`/run/colabos/colabos.lock`), so a snapshot cannot race another svc operation.

### doctor [--fix]
**Without `--fix`, doctor is strictly read-only**: no repair callback runs, so it never extracts, relinks, or restarts anything. The lock is taken for `--fix` only.

**With `--fix`**: the engine lock (`/run/colabos/colabos.lock`) is taken, so a repair cannot race a concurrent bootstrap/install/snapshot. A repair that fails is reported as `ERR` — never falsely as `[fix]`.

Checks (in order):
1. `$BASE` is a directory (fix: can't — ask user to mount Drive).
2. `zstd` is on PATH (fix: `apt-get install -y zstd`).
3. `/usr/local/bin/svc` executable shim invoking `python3 engine/svc` (fix: recreate shim).
4. `/etc/profile.d/colabos.sh` exists (fix: regenerate — atomic temp file + rename).
5. `/etc/profile.d/colabos-motd.sh` exists (fix: regenerate — atomic temp file + rename).
6. Per-app:
   - tarball exists.
   - the manifest's declared `[artifact].sha256` is a well-formed 64-char hex digest.
   - store directory exists (fix: run install_app).
   - **the extracted tree's content hash matches the hash in the store directory name** (fix: re-extract the artifact — a forced install, so a corrupted tree is actually healed instead of being skipped because the directory already exists). This is the slowest check — it hashes every store tree (~8 s for the devtools bundle).
   - live `/opt/colabos/<name>` symlink exists and points to the store (fix: recreate).
   - every bin in `bins[]` resolves to a real file inside the store AND `/usr/local/bin/<b>` is a symlink to it (compared via `os.path.realpath` on both sides — fixes shadowed/overwritten symlinks; fix: recreate).
   - every `[persist]` target is a symlink to the Drive source (fix: recreate).
   - `[health].command` exits 0 (servers and tools that declare one).
   - `[expose].health` exits 0 (servers). These probes verify the **real** exposure path — e.g. a server asserts its real exposure path actually answers, not just that the local process is alive.

Every manifest health probe is bounded (20 s), so a hung probe cannot stall the command.

Final line: `ALL CHECKS PASSED (Healthy)` or `ISSUES FOUND — run \`svc doctor --fix\` to auto-heal.`

### Auto-generated wrappers (shell)
`write_profile()` emits:
- `PATH=/usr/local/bin:$PATH`
- env exports from every `[env]` table (merged across apps; unique wins). Values are **shell-quoted** before being written into the profile.
- `TAILSCALE_HOSTNAME=colabos-node`.
- One generic `_colabos_wrap` function that dispatches by `$0`/first arg, records pre-mtime, runs the real command, and decides whether to snapshot:
  - Snapshot if argv[1] is exactly `update|upgrade|self-update` AND no no-op flag (`-h,--help,-v,--version,--dry-run,--dryrun,--dry,--report,--check,--list,-l`) is present AND exit status was 0.
  - **`install` is no longer an update verb** — `npm install <pkg>` does not trigger a 370.1 MiB snapshot.
  - Otherwise snapshot if the binary's mtime changed post-command (catches self-updaters). Mtime tracking is **sub-second** (`stat -c %.9Y`), so a self-updater that replaces the binary within the same wall-clock second is still detected.
  - Snapshots run inside a `flock -n 9 /run/colabos/colabos_snapshot.lock` subshell so concurrent invocations don't race.
- One thin wrapper function per bin that calls `_colabos_wrap <bin> "$@"`.

The profile and MOTD are written **atomically** (temp file + rename), so a Drive/FUSE interruption cannot truncate them.

Total ~120 lines regardless of bin count (vs. 14 KB hand-written before v1.1.1). Adding a bin to `bins[]` and re-bootstrapping creates the wrapper automatically.

### status
`svc status [name]` prints the health card per app. Persist sizing is **bounded** (at most 2000 entries); a truncated walk is reported as `>= <size> (partial)`. Walking the full Drive tree unbounded once took over 600 s. All manifest health probes are bounded (20 s).

## 4. app.toml Contract

```toml
[app]
name        = "devtools"
version     = "1.0.0"
type        = "tool"            # "tool" | "server"
description = "..."

[artifact]
file        = "devtools-1.0.0-a92aed243b76f7dc.tar.zst"
bins        = ["node", "npm", ...]

[persist]                                             # dotted keys must be quoted
"home/devtools/cargo" = "/root/.cargo"

[expose]                                             # servers only
port        = "22"
mode        = "tailnet"                              # "tailnet" | "funnel" | "none"
health      = "tailscale ip -4 2>/dev/null | grep -q '^100\\.'"

[env]
GOROOT = "/opt/colabos/devtools/lib_go"
```

## 5. Service Inventory (v1.1.8: 3 services)

### devtools v1.0.0 (tool)
- Artifact: `devtools-1.0.0-a92aed243b76f7dc.tar.zst` (~370.1 MiB, deterministic hash).
- 20 bins (`node, npm, npx, pnpm, yarn, bun, bunx, go, gofmt, rustc, cargo, rustup, uv, uvx, rg, fd, jq, fzf, tree, gh`).
- Persist: `/root/.cargo`, `/root/.npm`, `/root/.config/gh`.
- Versions: node v24.19.0, npm 11.17.0, bun 1.3.14, go 1.22.6, cargo 1.97.1, uv 0.12.5, rg 15.2.0, fd 8.3.1, gh 2.103.3, jq 1.6, fzf 0.72, tree 2.0.2.
- Auto-snapshot via wrappers.
- `tailscale`/`tailscaled` are owned by `tailscale-ssh`, not `devtools`.

**Rust layout** (lifecycle hook `apps/devtools.sh`):
- `RUSTUP_HOME = /content/drive/MyDrive/ColabOS/home/devtools/rustup` — persistent Drive state.
- The toolchain stays **inside the artifact** (`/opt/colabos/devtools/rustup/toolchains/`) and is **symlinked** into the persistent rustup home by `apps/devtools.sh`.
- rustup's **mutable state no longer lives in the artifact**: `settings.toml`, `downloads/`, `tmp/`, `update-hashes/` live on Drive. The hook never writes inside the artifact tree — doing so would invalidate the content hash.
- The `rustc`/`cargo` shims are rustup proxies using `exec -a`.
- The artifact's dead `cargo/` directory (15 identical rustup proxy copies + a stale cargo/env pointing at `/tmp/stage_devtools`) was removed.

### tailscale-ssh v1.2.3 (server, tailscale v1.104.5)
- Artifact: `tailscale-ssh-1.2.3-1d324134bdbbe442.tar.zst`.
- Bins: `tailscale`, `tailscaled`.
- Persist: `/var/lib/tailscale` (state, certs, logs, derpmap), `/root/.ssh/keys_backup` (the `keys_backup` persist mapping exists, but the hook copies the identity into `/root/.ssh` directly).
- The tailscaled state file is `home/tailscale-ssh/tailscale/tailscaled.state`; the socket is `/var/run/tailscale/tailscaled.sock`.
- Hostkeys: 4 files in `home/tailscale-ssh/ssh-hostkeys/` **copied** (not symlinked) to `/etc/ssh`; a missing `ssh_host_*_key.pub` is regenerated with `ssh-keygen -y`; canonical ed25519 pubkey ends `<YOUR_HOST_ED25519_KEY_SUFFIX>`.
- Permanent sshd policy is key-only (`PasswordAuthentication no`, `PermitRootLogin prohibit-password`).
- Lifecycle hook respects the sentinel directory `/var/run/colabos-cf-bootstrap/`; if present (signalling an external bootstrap session is active), it skips rewriting `sshd_config` and SIGHUP so an in-progress agent tunnel isn't killed.
- `tailscale serve --bg --tcp 22 tcp://127.0.0.1:22` exposes port 22 on the tailnet.
- Reverse-SSH config for the Oracle VPS peer (`gateway-vps`) auto-written as a managed `~/.ssh/config` block using `IdentityFile /root/.ssh/colabos_ssh` through `nc -X 5 -x 127.0.0.1:1055`.

**SSH hook hardening**:
- Every sshd PID candidate (pidfile **and** `pgrep` fallback) is verified through `/proc/<pid>/exe` (and `PPid: 1`) before SIGHUP.
- A failed Tailscale status lookup leaves the existing managed `gateway-vps` block unchanged (it is not replaced with a placeholder).
- `iproute2` (`ss`) is part of the apt preflight, and apt install failures are fatal.
- A running `tailscaled` is only reused when its `--state`/`--socket` arguments match; otherwise it is restarted.

### oh-my-pi v19.0.1 (tool)
- Artifact: `oh-my-pi-19.0.1-f93076d1a2cb38dc.tar.zst` (164.6 MiB; SHA-256 `3065ebbf4730797ea009be30c605f14292e622440be124cdabde5d37f960fd00`).
- Bins: `omp`.
- Persist: `/root/.omp` (agent.db, sessions, models.db, config, natives — no reinstall; auth inside persisted state from user setup).

**OMP hook hardening** (`apps/oh-my-pi.sh`):
- `/etc/profile.d/omp-web.sh` is written **atomically** (temp file + `mv`), mode `0600`, owner `root:root`, wiring keys and registering the `omp-db-sync` exit flush trap.
- Drive key files are `chmod 0600`; `$HOME_OMP/omp/run` is mode `0700`.
- Active SQLite databases (`agent.db`, `history.db`, `models.db`, `skill-descriptions.db`) are staged as real local files in `/run/omp-db` (0700), which is directory-bind-mounted onto `agent/` (while underlying Drive `agent/` is mounted at `/run/omp-agent-drive` and non-DB entries are symlinked locally from `/run/omp-db/`). This avoids storing any symlinks on Drive FUSE (which Drive syncs as plain text files) and keeps all DBs and `-wal`/`-shm` sidecars 100% local. A periodic `omp-db-sync --daemon` (60s, dirty-only) plus shell `EXIT` trap flush verified snapshots to `db_store/`.
- The hook **exits 1** if `omp` is missing or `omp --version` fails.

## 6a. Server boot-ordering rule

- `depends_on` is a list of app names. `install_levels()` groups apps into **levels**: level 0 = apps with no satisfied dependencies, level N = apps whose dependencies all live in levels < N.
- Bootstrap installs one level at a time. Every app in a level installs in parallel; **the next level starts only after every app in the current level installed and its lifecycle hook returned successfully**. A dependent app's hook therefore cannot start before its dependency's hook has finished.
- The previous implementation computed a topological sort and then discarded it, installing everything in one shared thread pool — so a dependent app could race its dependency.
- **Any server that needs Tailscale (Funnel, serve, or the mesh) MUST declare `depends_on = ["tailscale-ssh"]`** (or whichever unit provides the mesh). Otherwise it races tailscaled on cold boot.
- Server hooks that use the mesh MUST NOT `exit 1` when it is not ready yet. Start the service on loopback, then retry exposure in a background helper (see the service's lifecycle hook). A failed hook aborts the whole boot.
- The engine is **strict** at bootstrap: a missing dependency or a dependency cycle is a **hard error** (`FATAL: invalid dependency graph`), not a silent downgrade to a single level.

## 6. Snapshot (formal feature)

- Snapshot: deterministic repack (`tar --sort=name`); exact current-plus-one-prior pruning (app-scoped); TOML atomically rewritten (temp file + rename).
- **Reconciliation:** after packing, the live install is reconciled — store directory renamed to the new content-addressed stem, `/opt/colabos/<name>` repointed, binaries relinked, lifecycle hook re-run.
- **Exactly two artifacts per app are retained** (the current one plus one prior). For longer history, copy tarballs aside manually before snapshotting.

## 7. How to Add a New Service

The mandatory 7-step procedure lives in `docs/master/Agent.md` §6. It is the canonical copy; this document does not duplicate it to avoid drift.

## 8. SSH Security Model

- **Tailnet (permanent):** key-only. Single SSH key pair `colabos_ssh` is used for inbound auth (its pubkey is the only entry in `authorized_keys`) and outbound reverse-SSH to the Oracle VPS gateway peer `gateway-vps`. Host keys are stable across reclaims.
- The generated `sshd_config` contains `Subsystem sftp /usr/lib/openssh/sftp-server` (without it, every sftp/scp-over-sftp session fails) and a trailing `Include /etc/ssh/sshd_config.d/*.conf` — OpenSSH uses the first value obtained for most keywords, so hardened base settings come first and drop-ins cannot silently re-enable password auth.
- The SSH hook validates its own output with `sshd -t` before reloading, verifies sshd is actually listening on :22, verifies every sshd PID candidate through `/proc/<pid>/exe` (and `PPid: 1`) before SIGHUP, restarts `tailscaled` when the on-disk binary differs from the running one (and when its `--state`/`--socket` arguments do not match), and **fails loudly** if Tailscale is not authenticated or the serve mapping cannot be applied. A silent `|| true` previously let bootstrap report success with a dead SSH stack.
- The hook copies the single identity (`colabos_ssh`) into `/root/.ssh` directly and regenerates a missing host-key `.pub` with `ssh-keygen -y`. A failed Tailscale status lookup leaves the existing managed `gateway-vps` SSH config block unchanged.
- **Cloudflare tunnel (on-demand):** password + key enabled only while the helper is running. The helper generates a per-session random 20-char password, creates the sentinel directory so ColabOS boot doesn't downgrade it, and on `--close` or TTL expiry removes the sentinel and invokes the ColabOS lifecycle hook to restore key-only policy.
- Keys live on the user's Google Drive (FUSE mount, `uid=0,gid=0`); access control is inherited from the Google account.

## 9. Verified Facts & Timing

| Boot path | Target | Measured |
|---|---|---|
| Cold (first boot after reclaim, ~571.7 MiB to extract + server start) | ~20–40 s | extract-bound (dominated by tar) |
| Warm (symlinks already present, servers alive) | <0.4 s | ~0.39–0.49 s wall, ~0.08 s engine fast-path |
| Full `svc doctor` (hashes every store tree) | — | ~31 s |

### Boot preconditions
- `boot` requires **root** — the engine installs into `/opt` and `/usr/local/bin`.
- `boot` requires a **real Drive FUSE mount** at `/content/drive`. There is no "non-empty, continue" fallback: a directory that merely exists but is not a FUSE mount is refused, because it looks durable but dies with the VM. The mount must be a FUSE mount, not any other filesystem at that path.

## 10. Version

- v1.0.0 — 2026-08-22 — initial release.
- v1.1.1 — 2026-08-26 — "Agent-Proof" release: `svc status`, self-healing `svc doctor --fix`, deterministic hashes, auto-generated wrappers, snapshot serialization + false-positive fix, sentinel-aware lifecycle hook, single canonical SSH identity, cleaned stale tailscale auth-url, TOML quoting hygiene, bin resolver depth-3 walk, all docs updated.
- v1.1.4 — rollback command removed; snapshot kept the current tarball only.
- v1.1.5 — runtime smoke health for tool apps; snapshot retention changed to current plus one prior artifact; documentation drift corrected.
- v1.1.6 — correctness + durability pass (2026-10-25). Engine: read-only doctor without `--fix`, dependency-level bootstrap, artifact digest verification, bounded health-probe timeouts, `type -P` wrapper mtime fix, snapshot locking, `.bak-*` pruning, `svc --version`, doctor content-hash check. Scripts: resilient 9router backup loop + new restore path, secrets parsed as data, PID verification, loud SSH failures, sftp subsystem restored. Boot: real mount/precondition checks. Manifests: `[artifact].sha256` for every app, exposure probes that test the real exposure path. System: `/usr/local/bin` ownership corrected to `root:root`. Added `engine/selftest.py` (64 read-only regression checks).
- v1.1.7 — correctness + durability pass (2026-11-09).
  - Engine: `svc snapshot` reconciles the live install (store rename, symlink repoint, binary relink, lifecycle hook re-run); `svc doctor --fix` re-extracts a corrupted store, takes the engine lock, and reports failed repairs as `ERR`; `svc install --force` re-extracts even when the store dir exists.
  - Durability: manifest/profile/MOTD writes are atomic (temp file + rename); all manifest health probes are bounded (20 s), including in `install` and `status`; a manifest-declared binary that cannot be resolved fails the install; a missing dependency or dependency cycle is a hard error at bootstrap; declared binaries are chmod'ed 0755 before hashing; persist rescue backups use unique names (timestamp + pid).
  - Wrappers: `install` removed as an update verb (only `update`/`upgrade`/`self-update` snapshot); sub-second mtime tracking (`stat -c %.9Y`); manifest env values shell-quoted.
  - `svc status`: persist sizing bounded to 2000 entries, reported as `>= size (partial)`.
  - Boot: a real Drive FUSE mount is mandatory (no "non-empty, continue" fallback) and root is required.
  - Services: exactly 3 (devtools, tailscale-ssh, oh-my-pi); the previously shipped fourth service was removed; devtools rebuilt at `a92aed243b76f7dc` (~370.1 MiB) with rustup's mutable state on persistent Drive.
  - SSH hook: verified sshd PID before SIGHUP; managed `gateway-vps` block preserved on status failure; host-key `.pub` regeneration; `iproute2` apt preflight with fatal apt failures; `tailscaled` argument-match restart check.
  - OMP hook: atomic `/etc/profile.d/omp-web.sh` write (0600 root:root), Drive key files 0600, `$HOME_OMP/omp/run` 0700, and the hook exits 1 when `omp` is missing or `omp --version` fails.
  - Engine self-test: initially 96 checks; current suite is 145/145.

### Live consistency addendum

- Single-binary apps declare `[artifact].version_bin`; OMP declares `version_bin = "omp"`. Snapshot uses the binary-reported version after a native update.
- The SSH hook retries an empty peer map (`12 × 5 s`) before deciding peer state. Status failures and persistently empty maps preserve the existing managed SSH block.
- Drive-side SSH identities and host private keys are enforced at mode 0600. `/root/.ssh/config` is written mode 0600.
- OMP current-plus-prior artifacts are 19.0.1 and 19.0.0.

### OMP daemon IPC and SQLite database boundary

Persistent OMP configuration (`config.yml`, `models.yml`), prompt templates, and conversation sessions remain directly on Drive-backed `~/.omp`. Daemon brokers, leases, tokens, and Unix sockets do not: the lifecycle hook makes persisted `~/.omp/run` a symlink to local `/run/omp-runtime`, created as root mode 0700. This split is required because Drive FUSE supports ordinary files but returns ENOTSUP for Unix-socket bind.

Similarly, active SQLite databases (`agent.db`, `history.db`, `models.db`, `skill-descriptions.db`) require POSIX advisory locks and shared memory (`-wal` and `-shm`), which network FUSE filesystems do not support reliably during VM reclaim or network latency spikes. The lifecycle hook (`apps/oh-my-pi.sh`) bind-mounts Drive `agent/` to `/run/omp-agent-drive`, stages the 4 SQLite databases as real local files in `/run/omp-db` (mode 0700) with local symlinks to `/run/omp-agent-drive/*` for all non-DB files/dirs, and directory-bind-mounts `/run/omp-db` onto `~/.omp/agent/`. This avoids storing symlinks inside Drive FUSE (which Google Drive turns into plain text files on revalidation) while keeping both `.db` files and `-wal`/`-shm` sidecars 100% off Drive FUSE. An atomic backup utility (`/usr/local/bin/omp-db-sync`) uses the native SQLite backup API and `PRAGMA quick_check;` via a periodic background daemon (`--daemon --interval 60`, dirty-only) and a shell `EXIT` trap to flush integrity-verified snapshots back to `home/oh-my-pi/omp/db_store/`.
