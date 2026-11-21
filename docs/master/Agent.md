# ColabOS Agent Knowledge Base - Single Source of Truth (v1.1.8)

> **Zero-Context Recovery Guarantee:** An autonomous agent with no prior memory, reading only this document, can fully understand and operate ColabOS — purpose, architecture, invariants, commands, and the mandatory new-service flow.

---

## 1. What is ColabOS

ColabOS turns a free Google Colab VM into a persistent service platform. The user's laptop has 8 GB RAM; Colab provides a larger VM and 108 GB of mounted Google Drive but wipes root on every reclaim. After `bash /content/drive/MyDrive/ColabOS/boot`, tools, service wrappers, and SSH are ready in ~0.4 s warm / ~20–40 s cold, so the machine behaves more like a local box that already has everything set up.

The five axioms:
> **VM is CPU, Drive is Disk, Hash is Truth, Overlay is View, Mesh is Address.**

- **VM is CPU.** Root FS is overlay on `/` (ephemeral Docker/Colab layer). Nothing in `/` survives restart.
- **Drive is Disk.** `mount | grep drive` → `drive on /content/drive type fuse.drive (rw,...)`. Persistent root = `/content/drive/MyDrive/ColabOS`.
- **Schema is versioned.** Every TOML `[app]` section must include `schema_version = "1"`. If a TOML declares a schema_version newer than what the current engine understands, `svc bootstrap`/`list`/`doctor` refuse to continue and print an upgrade instruction. This prevents accidentally running an old engine against a new-format TOML.
- **Hash is Truth.** Artifacts are named `<name>-<version>-<16-char-sha256>.tar.zst`. Hashes are computed with `tar --sort=name -cf - -C <dir> . | sha256sum | cut -c1-16` (deterministic as of v1.1.1). Doctor verifies the installed store directory basename matches the hash in `<name>.toml`.
- **Overlay is View.** Binaries extract to `/opt/colabos/store/<name>-<ver>-<hash>/` (atomic `.tmp` + rename), symlinked from `/opt/colabos/<name>`, bins symlinked to `/usr/local/bin`, state symlinked from `$BASE/home/<svc>/...` into `/root, /var/lib, /etc`.
- **Mesh is Address.** No public IP and no `/dev/net/tun`. Tailscale runs `--tun=userspace-networking --socks5-server=127.0.0.1:1055`. Stable identity `colabos-node.example-tailnet.ts.net` (IP `100.64.0.1`) on tailnet `example-tailnet.ts.net`. Ports via `tailscale serve` (private) / `tailscale funnel` (public).

---

## 2. Verified Facts

- **FUSE perf:** small write ~25 ms vs tmpfs ~1 ms (~25× slower). Execute binaries from `/opt/colabos`; only store archives and state on Drive.
- **FUSE supports +x.** Small scripts (`boot`, `engine/svc`) execute off Drive directly.
- **Tailscale userspace is mandatory** (no TUN in Colab).
- **`zstd`** is required; `boot` installs it with `apt-get install -y zstd` if missing.
- **Current-plus-prior pruning**: `svc snapshot` keeps the current tarball and one prior tarball per app; older ones are deleted.
- **Warm boot budget < 0.4 s** (measured 0.39–0.49 s wall, ~0.08 s engine fast-path). The bootstrap fast path uses a SHALLOW doctor: it skips the content-hash comparison and the full manifest health commands, and instead does a cheap TCP connect to each server's exposed port. A full `svc doctor` takes ~31 s because it hashes every store tree.
- **Deterministic hash** (v1.1.1+): `tar --sort=name` ensures a directory with identical content always produces the same hash regardless of filesystem order.
- **Permanent SSH policy = key-only** (`PasswordAuthentication no`, `PermitRootLogin prohibit-password`). Single key identity `colabos_ssh`.

- **Profile wrappers are auto-generated** from TOML `bins[]`. Do NOT hand-edit `/etc/profile.d/colabos.sh`; it will be overwritten on next bootstrap.
- **Shell wrapper lock** at `/run/colabos/colabos_snapshot.lock` prevents concurrent auto-snapshots from racing.

---

## 3. Layout & Constants

```
BASE=/content/drive/MyDrive/ColabOS
├── boot                              (2.5 KB, bash)
├── engine/svc                        (~76 KiB, Python 3, v1.1.8)
├── engine/selftest.py                (read-only regression suite, 145 checks)
├── apps/                             tar.zst + <name>.toml + <name>.sh (lifecycle hook, any type; servers use it for daemons)
├── home/<name>/...                   persistent state (symlinked into VM)
└── docs/
    ├── master/{README,Architecture,Agent,User_Manual}.md
    └── <service>/{README,Build_Log,User_Manual}.md
```

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

Services in v1.1.8 (**3**):
1. `devtools` v1.0.0 (tool, hash `a92aed243b76f7dc`, 20 bins)
2. `tailscale-ssh` v1.2.3 / tailscale v1.104.5 (server, tailnet :22 key-only, hash `1d324134bdbbe442`)
3. `oh-my-pi` v19.0.1 (tool, hash `f93076d1a2cb38dc`, 1 bin `omp`, NVIDIA provider, auth in persisted state)

---

## 4. Engine Commands

```bash
python3 $BASE/engine/svc bootstrap              # flock + parallel install + generate profile
python3 $BASE/engine/svc list                   # table of apps
python3 $BASE/engine/svc status [name]          # health card with hash verification
python3 $BASE/engine/svc install <name> [--force]  # extract + symlink + persist + server hook
python3 $BASE/engine/svc snapshot <name> [--version X]  # deterministic repack + retain current and one prior
python3 $BASE/engine/svc doctor [--fix]         # verify; --fix auto-heals
python3 $BASE/engine/svc logs <name>             # inspect known log files for a service
python3 $BASE/engine/svc doc-table [--json]      # Markdown/JSON state table from live manifests
```

### install summary
- `flock LOCK_FILE` (bootstrap holds it).
- If the manifest declares `[artifact].sha256`, the tarball's sha256 is verified **before** extraction; a mismatch aborts the install (fail closed).
- Extract with `tar -I 'zstd -T0' -xf` into `.tmp`, atomic rename, then re-hash the extracted tree and compare it with the hash in the store directory name.
- `--force` re-extracts the artifact **even when the store directory already exists** — the repair path for a corrupted or tampered tree.
- Declared binaries are chmod'ed to 0755 **before** the tree is hashed, so an archived 0644 mode no longer causes a false content-hash mismatch on the next doctor run.
- A manifest-declared binary that cannot be resolved **fails the install** (it is not silently skipped). Candidate resolution is deterministic (sorted).
- Every manifest health probe is bounded (20 s), including the probes run during `install`.
- Link `/opt/colabos/<name> -> $STORE_OPT/<stem>`.
- Bins resolved via `find_bin()` (sorted `*/bin/<b>` walk at depths 0–3, e.g. `bin/<b>` or `lib/node/bin/npm`), chmod 0755, symlink into `/usr/local/bin`.
- Persist: `mkdir -p` Drive source, rescue existing real dirs to `dst.bak-<timestamp>-<pid>` (unique names — two rescues in the same second cannot nest; only the newest rescue copy per target is kept), symlink dst → src.
- Servers run `bash apps/<name>.sh`; on success use `tailscale serve` or `tailscale funnel` per `expose.mode`.

### bootstrap summary
- Apps are installed in **dependency levels**; a level starts only after every app in the previous level installed and its lifecycle hook returned successfully.
- A missing dependency or a dependency cycle is a **hard error**: bootstrap aborts with `FATAL: invalid dependency graph` instead of silently downgrading the ordering guarantee.

### snapshot summary
- Hash live store deterministically (`tar --sort=name`).
- Pack with `zstd -6 -T0`; print size + elapsed seconds.
- Rewrite `[artifact].file` in TOML via the simple writer (lists, bools, strings — sufficient for our schema). Manifest writes are atomic (temp file + rename).
- **Reconciles the live install**: the store directory is renamed to the new content-addressed stem, `/opt/colabos/<name>` is repointed, `/usr/local/bin` binaries are relinked, and the lifecycle hook is re-run. The manifest and the installation never diverge after a snapshot.
- Prunes app-scoped to **exactly the current artifact plus one prior artifact**.
- Takes the engine lock (`/run/colabos/colabos.lock`), so a snapshot cannot race another svc operation.

### doctor --fix self-healing
**Without `--fix`, doctor is strictly read-only** — repair callbacks only run when `--fix` is passed.
(It previously ran `install_app` — extract + lifecycle hook — even on a plain `svc doctor`, so a
read-only health check could restart services.)

With `--fix` it re-creates:
- `/usr/local/bin/svc -> engine/svc` symlink,
- `/etc/profile.d/colabos.sh` and `/etc/profile.d/colabos-motd.sh` (by calling `write_profile()` / `write_motd()`; both are written atomically — temp file + rename),
- any missing `/usr/local/bin/<bin>` symlinks (resolves through `find_bin`),
- missing persist directory symlinks,
- installs `zstd` if absent,
- extracts missing store directories by recursively calling `install_app`,
- **re-extracts a corrupted store tree** (forced install), so a detected tamper is actually healed.

`doctor --fix` **takes the engine lock**, so it cannot race a concurrent bootstrap/install/snapshot.
A repair that fails is reported as `ERR` — never falsely as `[fix]`.

It compares `os.path.realpath(dst) == os.path.realpath(src)` so it correctly handles both sides being symlinks into store.

Doctor also checks, per app: the tarball exists, the declared `[artifact].sha256` is well-formed,
the **extracted tree's content hash matches the hash in the store directory name** (tamper
detection — this is the slowest check, ~8 s for the devtools bundle), the live symlink, every bin,
every persist target, `[health].command`, and `[expose].health`. Every manifest health probe is
bounded (20 s), so a hung probe cannot stall the command.

### Engine self-test
```bash
python3 $BASE/engine/selftest.py          # 145 checks, read-only
python3 $BASE/engine/selftest.py -v       # verbose
```
Covers TOML parsing, dependency ordering (cycles, missing deps), content hashing with exclusions,
artifact digest tamper detection, health-probe timeouts, doctor read-only behaviour, manifest
schema + digest integrity, the CLI surface, and bash syntax of every lifecycle hook.
The suite never mutates live state — it stubs `write_profile()` before exercising `--fix`.

### Wrapper logic (shell, generated)
- Capture the binary mtime with sub-second precision (`stat -c %.9Y`), run `command <bin> "$@"`, capture exit status.
- Snapshot if:
  - argv[1] ∈ {update, upgrade, self-update} AND no no-op flag (`-h,--help,-v,--version,--dry-run,--dryrun,--dry,--report,--check,--list,-l`) AND exit == 0; OR
  - the binary's mtime changed after invocation (self-updater case). Sub-second mtime tracking catches a self-updater that replaces the binary within the same wall-clock second.
- **`install` is NOT an update verb** — `npm install <pkg>` no longer triggers a 370.1 MiB snapshot. Only `update`, `upgrade`, and `self-update` do.
- Manifest `[env]` values are **shell-quoted** before they are written into the generated profile.
- Snapshots run inside `(flock -n 9 ... ) 9>/run/colabos/colabos_snapshot.lock` so concurrent runs serialize (the first one snapshots, later ones exit silently).

### Boot preconditions
- `boot` requires **root** (the engine installs into `/opt` and `/usr/local/bin`).
- `boot` requires a **real Drive FUSE mount** at `/content/drive`: there is no "non-empty, continue" fallback. A directory that merely exists but is not a FUSE mount is refused, because it looks durable but dies with the VM.

### Persistent-state layout
- SSH host keys live in `home/tailscale-ssh/ssh-hostkeys/` and are **copied** into `/etc/ssh` (not symlinked), so the daemon always reads local files.
- The tailscaled state file is `home/tailscale-ssh/tailscale/tailscaled.state` (passed to the daemon as `--state=`); the socket is `/var/run/tailscale/tailscaled.sock`.
- The `keys_backup` persist mapping exists (`home/tailscale-ssh/keys` → `/root/.ssh/keys_backup`), but the SSH hook **copies the identity into `/root/.ssh` directly** (`/root/.ssh/colabos_ssh`, `.pub`, `authorized_keys`).
- **Single SSH identity: `colabos_ssh` only.** No other key pair is shipped.
- `svc status` persist sizing is **bounded** (at most 2000 entries). A partial walk is reported as `>= <size> (partial)`. Walking the full Drive tree unbounded once took over 600 s.

### devtools Rust layout
- `RUSTUP_HOME = /content/drive/MyDrive/ColabOS/home/devtools/rustup` (persistent Drive state).
- The Rust **toolchain stays inside the artifact** (`/opt/colabos/devtools/rustup/toolchains/`) and is **symlinked** into the persistent rustup home by `apps/devtools.sh`.
- rustup's **mutable state no longer lives in the artifact**: `settings.toml`, `downloads/`, `tmp/`, `update-hashes/` live on Drive. A rustup run must never write inside the artifact tree — it would invalidate the content hash.
- The `rustc`/`cargo` shims are rustup proxies using `exec -a`.

### SSH hook hardening (`apps/tailscale-ssh.sh`)
- **Verified PID before SIGHUP**: every sshd PID candidate (pidfile and `pgrep` fallback) is checked against `/proc/<pid>/exe` (and `PPid: 1`) before the daemon is signalled.
- **Managed `gateway-vps` block preserved on status failure**: if the Tailscale status lookup fails, the existing managed SSH config block is left unchanged instead of being replaced with a placeholder.
- **Host-key `.pub` regeneration**: a missing `ssh_host_*_key.pub` is regenerated with `ssh-keygen -y`.
- **iproute2 preflight**: `ss` is installed via apt, and apt install failures are fatal.
- **tailscaled argument-match restart check**: a running `tailscaled` is only reused when its `--state`/`--socket` arguments match; otherwise it is restarted.

### OMP hook hardening (`apps/oh-my-pi.sh`)
- `/etc/profile.d/omp-web.sh` is written **atomically** (temp file + `mv`), mode `0600`, owner `root:root`.
- Drive key files are `chmod 0600`.
- `$HOME_OMP/omp/run` is mode `0700`.
- The hook **exits 1** if `omp` is missing or `omp --version` fails.

### Sentinel protection for SSH agent sessions

The sentinel file `/var/run/colabos-cf-bootstrap` prevents `svc bootstrap` from destroying an active agent SSH session. Specifically, `apps/tailscale-ssh.sh` checks for this sentinel and skips:
- writing `/etc/ssh/sshd_config`,
- running `sshd -t && kill -HUP $(cat /var/run/sshd.pid)`.

- **When you are operating inside an agent session over Cloudflare, always create the sentinel before running `svc bootstrap`** — otherwise you lock yourself out. If you use the shipped v3 helper, it does this automatically.

---

## 5. TOML Contract

```toml
[app]
name = "devtools"
version = "1.0.0"
type = "tool"                                    # "tool" | "server"
description = "..."
log = "/tmp/app.log"                             # optional; point at Drive for durable logs
hash_exclude = [".next"]                         # optional; excluded from the content HASH only

[artifact]
file = "devtools-1.0.0-a92aed243b76f7dc.tar.zst"
sha256 = "a4ba1e7448e70f61459780e01c6044bc228b6dd1583e768a13410945008a0e8b"  # tarball digest, verified before extraction
bins = ["node","npm", ...]

[persist]                                        # dotted keys MUST be quoted for tomllib
"home/devtools/cargo" = "/root/.cargo"

[expose]                                         # servers only
port = "22"
mode = "tailnet"                                 # "tailnet" | "funnel" | "none"
health = "tailscale ip -4 2>/dev/null | grep -q '^100\\.'"

[health]                                         # optional; what `svc doctor` runs
command = "[ -L /root/.omp/run ] && [ -d /run/omp-runtime ] && [ -w /run/omp-runtime ]"

[env]
GOROOT = "/opt/colabos/devtools/lib_go"
```

Notes:
- `hash_exclude` is for runtimes that write into their own install tree (e.g. a Next.js
  `.next` route cache). It applies to **hashing only** — snapshots still archive everything,
  so a fresh extract stays runnable.
- `[expose].health` is the HTTP probe shown by `svc status`; `[health].command` is the stronger
  process+HTTP check `svc doctor` runs. They are not duplicates.
- `mode` is documentation-grade when a `.sh` hook exists: the engine skips its own
  `maybe_apply_network` in that case, so the hook owns the actual exposure.

---

## 6. Mandatory 7-Step New-Service Flow

When asked to "make X persist" or add a new service, do NOT jump into writing TOML + tarballs. Steps, in order. Step 5 is a HARD GATE.

```
[1 Context] → [2 Plain Setup] → [3 Credentials]
                                        │
                                        ▼
[6 ColabOS Persistence] ◄─ [5 User Verify] ◄─ [4 Live Test]
         │
         ▼
[7 Update Docs] → [svc doctor: ALL CHECKS PASSED]
```

### Step 1 — Full Context
Ask/research: purpose, normal Linux install/run instructions, state/config/credential/database files, which of those MUST survive reclaim (state/creds/DBs → `home/<name>/`) vs are rebuildable (binaries/caches).

### Step 2 — Plain Setup First (NO persistence)
Install/configure exactly as on any machine. No Drive symlinks, no TOML, no tarballs. Get it running plain.

### Step 3 — Credentials
- API keys/tokens: ASK THE USER. Never invent/hardcode.
- OAuth / interactive login: launch the process; make the user complete browser consent.

### Step 4 — Live Test
Start the service, exercise a real operation (store data, query endpoint, run command). Confirm it works on THIS VM.

### Step 5 — User Verification (REQUIRED GATE)
Explicitly ask the user to confirm it works. Only proceed after they say yes — many services don't create DBs/config dirs until first real run, and you can't persist files that don't exist.

### Step 6 — ColabOS Persistence (after approval)
1. Stage binaries to `/tmp/stage_<name>/bin/*`, `chmod +x`.
2. Compute hash & build artifact:
   ```bash
   HASH=$(tar --sort=name -cf - -C /tmp/stage_<name> . | sha256sum | cut -c1-16)
   tar --sort=name -I 'zstd -6 -T0' -cf $BASE/apps/<name>-1.0.0-${HASH}.tar.zst -C /tmp/stage_<name> .
   ```
3. Write `apps/<name>.toml` with sections `[app]`, `[artifact]` (file = new tarball, `sha256` = `sha256sum` of that tarball, bins list), `[persist]` (quoted Drive-relative keys), `[expose]` (port, mode, health — servers only), `[env]`. For a server that uses Tailscale (Funnel, serve, or the mesh), add `depends_on = ["tailscale-ssh"]` (or whichever app provides the mesh) so it cannot race tailscaled on cold boot. Set `[app].log` to a Drive path (`$BASE/home/<name>/logs/...`) so logs survive reclaim; `/tmp` is wiped. The `[expose].health` probe must test the **real** exposure path (route present + public/tailnet URL answering), not just local liveness.
4. For servers: write `apps/<name>.sh` lifecycle hook (install deps, write config, validate with `-t`/equivalent, start with `setsid nohup ... > $BASE/home/<name>/logs/<name>.log 2>&1 < /dev/null &`, expose via `tailscale serve`/`funnel` per mode). **The hook MUST NOT `exit 1` just because Tailscale is not ready yet** — start the service on loopback, then retry exposure in a detached background helper (see the service's lifecycle hook). A failed hook aborts the whole boot. If you might start sshd or touch `sshd_config`, check for `/var/run/colabos-cf-bootstrap/` and skip the SIGHUP if the sentinel exists.
5. Install via the engine:
   ```bash
   python3 $BASE/engine/svc install <name>
   python3 $BASE/engine/svc doctor --fix    # must end ALL CHECKS PASSED
   ```

### Step 7 — Update Docs (agent obligation)
Create three files in `docs/<name>/`:
1. `README.md` — What it is / How the user runs it / Setup & credentials / Persistence mechanism / Reclaim safety / Troubleshooting.
2. `Build_Log.md` — Date, version, hash, artifact size, build commands, verified paths.
3. `User_Manual.md` — Step-by-step human guide.

Update master docs:
- Add a row to the services table in `docs/master/README.md`.
- Update service count and the Service Inventory section (§5) in `docs/master/Architecture.md` and root `README.md`.
- Update this file (`Agent.md`) only if the theory, constants, commands, the 7-step flow itself, or critical rules change.
- Update root `README.md` version table + changelog.

Then simulate reclaim: `rm /opt/colabos/<name>; python3 $BASE/engine/svc install <name>; doctor` — must pass and the service must come up without data loss.

---

## 7. Critical Rules

1. **Always run `svc doctor` (or `svc doctor --fix`) after every change.** Final line MUST be `ALL CHECKS PASSED (Healthy)`.
2. **Never execute binaries from Drive FUSE.** Only `boot` and `engine/svc` run off Drive (they're small); everything else executes from `/opt/colabos` after extraction.
3. **Use atomic operations**: extract to `.tmp` then `os.rename()`; acquire `flock` on LOCK_FILE; snapshot lock on `/run/colabos/colabos_snapshot.lock`.
4. **Keep host keys stable**: copy (don't symlink) `home/tailscale-ssh/ssh-hostkeys/ssh_host_{ed25519,rsa}_key{,.pub}` to `/etc/ssh/`, `chmod 600`, `sshd -t`, then HUP sshd. Canonical ed25519 host pubkey ends `<YOUR_HOST_ED25519_KEY_SUFFIX>`.
5. **Single SSH identity.** `colabos_ssh{,.pub}` in `home/tailscale-ssh/keys/` is the only key pair shipped. Do not create extra keys. It is used both for inbound auth (pubkey in `authorized_keys`) and outbound reverse-SSH to the Oracle VPS gateway peer `gateway-vps`.
6. **Sentinel awareness.** Before any code path writes `/etc/ssh/sshd_config` or does `kill -HUP sshd`, check for `/var/run/colabos-cf-bootstrap/` and SKIP both if it exists. Otherwise you lock out any agent connected over the Cloudflare tunnel.
7. **`$BASE` is hardcoded in three places**: `engine/svc:~10` (`BASE =`), `boot:3` (`BASE=`), and each `apps/*.sh` lifecycle hook's `BASE=`. If you move BASE, update all three.
8. **Warm boot budget < 0.4 s.** Do not add slow I/O to the bootstrap hot path.
9. **Do NOT hand-edit `/etc/profile.d/colabos.sh`.** It is auto-generated from TOML by `write_profile()`. Add a new wrapper by adding the bin to an app's `bins = []` array and re-bootstrapping.
10. **Quoted TOML keys.** Dotted keys (e.g. `"home/devtools/cargo"`) MUST be quoted for Python stdlib `tomllib`.
11. **Deterministic hashes.** Always use `tar --sort=name` when computing or packing snapshots. Never use plain `tar -cf` for hashing.
12. **Current plus prior.** After a snapshot, the current and immediately previous tarballs are retained; older ones are pruned.
13. **Docs rule.** When adding a service you MUST create the three per-service docs AND update the master index, architecture inventory, root README, and changelog. Keep Agent.md §6 canonical; do not duplicate it in other docs.
14. **Declare `[artifact].sha256` for every new app.** The engine verifies it before extraction and fails closed on mismatch. Compute it with `sha256sum apps/<name>-<ver>-<hash>.tar.zst`.
15. **Exposure probes must test the real exposure path.** A local-only check passes even when Funnel/serve is silently down. Assert the route exists *and* the public/tailnet URL answers.
16. **Never source a secrets file as shell code.** Parse it as data with a strict key allow-list. Sourcing executes any command substitution inside a value and aborts the hook on a syntax error.
17. **Never kill a pid you have not verified.** Confirm `/proc/<pid>/cmdline` identifies the expected service before signalling it; a stale pidfile can point at an unrelated process after PID reuse.
18. **Required steps must fail loudly.** Do not end a lifecycle hook with `|| true` on a step whose failure means the service is broken — a swallowed error lets bootstrap report success with a dead stack.
19. **`/usr/local/bin` must stay `root:root`.** A non-root-owned binary directory lets an unprivileged user replace binaries that root executes.
20. **Run `engine/selftest.py` after changing the engine** — 145 read-only checks covering parsing, ordering, hashing, digests, timeouts, version drift, hook contracts, and shell generation.

---

## 8. Out-of-Band Tools You May Be Asked About

- **`/content/drive/MyDrive/Colab Notebooks/`** — regular Colab notebooks, out of scope.

---

## 9. Quick Commands (cheat sheet)

```bash
# boot
bash /content/drive/MyDrive/ColabOS/boot

# health + inventory
python3 /content/drive/MyDrive/ColabOS/engine/svc list
python3 /content/drive/MyDrive/ColabOS/engine/svc status
python3 /content/drive/MyDrive/ColabOS/engine/svc doctor
python3 /content/drive/MyDrive/ColabOS/engine/svc doctor --fix

# package management
python3 /content/drive/MyDrive/ColabOS/engine/svc install <name>
python3 /content/drive/MyDrive/ColabOS/engine/svc snapshot <name>

# mesh
tailscale status
ssh gateway-vps     # reverse-SSH to the Oracle VPS gateway via SOCKS5

```

---

## 10. Changelog

- v1.0.0 (2026-08-22) — initial release: boot, install, snapshot (keep-current-only), doctor, 2 services (devtools, tailscale-ssh).
- v1.1.1 (2026-08-26) — "Agent-Proof" hardening: added `svc status`; `svc doctor --fix` self-heals; deterministic `tar --sort=name` hashes; auto-generated shell wrappers (120 lines vs 14 KB hand-written) with snapshot serialization and false-positive fixes; sentinel-aware tailscale-ssh lifecycle hook; v3 Cloudflare tunnel helper (random per-session password, TTL auto-close, line-buffered output, PowerShell example); single canonical SSH identity `colabos_ssh`; removed stale tailscale auth-url; dotted TOML keys quoted for tomllib; depth-3 bin resolution; warm boot timing preserved (0.19–0.27 s).
- v1.1.4 — rollback command removed; snapshot kept the current tarball only.
- v1.1.6 (2026-10-25) — correctness + durability pass. Engine: read-only doctor without `--fix`; dependency-level bootstrap so a dependent hook cannot race its dependency; `[artifact].sha256` verified before extraction (fail closed) plus post-extract tree re-hash; bounded health-probe timeouts; wrapper mtime fix via `type -P`; snapshot takes the engine lock; `.bak-*` rescue pruning; `svc --version`; doctor verifies each app's content hash. Scripts: resilient 9router backup loop (survives failed rounds, integrity-gated, sidecar-aware) + new `9router-restore.sh`; secrets parsed as data with an allow-list; secrets validated before the running server is touched; PID verified before kill; SSH hook fails loudly, validates `sshd -t`, restarts `tailscaled` on binary change, restores the missing `Subsystem sftp` line and an early `Include` for drop-ins. Boot: Drive-mount and toolchain preconditions with specific errors. Manifests: digest for every app; exposure probes that verify the real exposure path. System: `/usr/local/bin` → `root:root`. Added `engine/selftest.py` (64 read-only regression checks).

- v1.1.7 — correctness + durability pass (2026-11-09).
  - Engine: `svc snapshot` reconciles the live install (store rename, symlink repoint, binary relink, lifecycle hook re-run); `svc doctor --fix` re-extracts a corrupted store, takes the engine lock, and reports failed repairs as `ERR`; `svc install --force` re-extracts even when the store dir exists; manifest/profile/MOTD writes are atomic; all manifest health probes are bounded (20 s); a manifest-declared binary that cannot be resolved fails the install; a missing dependency or dependency cycle is a hard error at bootstrap; declared binaries are chmod'ed 0755 before hashing; persist rescue backups use unique names (timestamp + pid).
  - Wrappers: `install` removed as an update verb (only `update`/`upgrade`/`self-update` snapshot); sub-second mtime tracking; manifest env values shell-quoted.
  - `svc status`: persist sizing bounded to 2000 entries, reported as `>= size (partial)`.
  - Boot: a real Drive FUSE mount is mandatory (no "non-empty, continue" fallback) and root is required.
  - Services: exactly 3 (devtools, tailscale-ssh, oh-my-pi); the previously shipped fourth service was removed; devtools artifact rebuilt at `a92aed243b76f7dc` with rustup's mutable state moved to persistent Drive (`RUSTUP_HOME=/content/drive/MyDrive/ColabOS/home/devtools/rustup`) and the artifact's `cargo/` removed.
  - SSH hook: verified sshd PID before SIGHUP; managed `gateway-vps` block preserved when Tailscale status lookup fails; host-key `.pub` files regenerated via `ssh-keygen -y`; `iproute2` added to the apt preflight with fatal apt failures; running `tailscaled` reused only when its `--state`/`--socket` arguments match.
  - OMP hook: atomic `/etc/profile.d/omp-web.sh` write (0600 root:root), Drive key files 0600, `$HOME_OMP/omp/run` 0700, and the hook exits 1 when `omp` is missing or `omp --version` fails.
  - Engine self-test: initially 96 read-only checks; the current suite is 145/145.

## 11. Post-v1.1.7 live consistency rules

21. **Single-binary apps declare `[artifact].version_bin`.** Native updaters can replace a live binary without touching the manifest. Snapshot must use the binary-reported version so the artifact name, manifest, store directory, and executable cannot disagree.
22. **An empty Tailscale peer map is transient until proven otherwise.** The SSH hook retries peer discovery for up to 60 seconds. It never replaces a working managed SSH block after a failed or still-empty status read.
23. **Persisted audit/session output must not contain credential literals.** Search by exact secret value without printing it, redact leaked copies atomically, and rotate any leaked runtime-only token. Provider API keys require provider-side rotation if exposure may have left Drive revision history.
24. **Keep daemon IPC off Drive FUSE.** OMP state and sessions persist under `~/.omp`, but Unix sockets and broker leases resolve through `~/.omp/run`, which is a symlink to local `/run/omp-runtime` (0700). Drive FUSE returns ENOTSUP for Unix-socket bind and must never host daemon IPC.

25. **Rule 25:** Never host active SQLite databases or POSIX symlinks directly on Drive FUSE. Isolate active DB directories via directory-level bind mounts onto local tmpfs with local passthrough symlinks for static assets, and persist changes atomically via the SQLite Online Backup API.
---

*End of Knowledge Base v1.1.8 — Zero-context recovery complete.*
