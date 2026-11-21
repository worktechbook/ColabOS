# oh-my-pi v19.0.1 - README

> omp coding agent CLI for ColabOS v1.1.8. IDE-wired fork of Pi with Rust core, TUI + `-p` + RPC/ACP, user-configured provider.

## Artifact

Current: `oh-my-pi-19.0.1-f93076d1a2cb38dc.tar.zst` (164.6 MiB) in `/content/drive/MyDrive/ColabOS/apps/`
SHA-256: `3065ebbf4730797ea009be30c605f14292e622440be124cdabde5d37f960fd00`
Binary: `omp` v19.0.1; `[artifact].version_bin = "omp"` keeps native updates, snapshots, and manifest versions aligned.

## Bins (1)

`omp`

## Persist

- `home/oh-my-pi/omp -> /root/.omp` (Tiered Persistence: `config.yml`, `models.yml`, `sessions/`, prompts live on Drive; active SQLite databases are staged locally in `/run/omp-db`, which is directory-bind-mounted onto `agent/` (with non-DB entries symlinked locally to `/run/omp-agent-drive/*`), synced via `omp-db-sync` to `home/oh-my-pi/omp/db_store/` — survives reclaim, zero FUSE WAL lock corruption)
- `home/oh-my-pi/firecrawl.key` (600, web-search API key on Drive, never in artifact; hook exports it via `/etc/profile.d/omp-web.sh`)
- `home/oh-my-pi/nvidia.key` (600, NVIDIA provider API key on Drive, never in artifact; hook exports it as `NVIDIA_API_KEY`)

NOT persisted: `/root/.bun` globals, `/root/.local/bin` (ephemeral install locations). After reclaim use `/usr/local/bin/omp` via PATH/wrapper.

`/root/.omp` is a **Drive symlink**, so databases, sessions, configuration, and browser profiles persist. Daemon IPC is the deliberate exception: the `~/.omp/run -> /run/omp-runtime` symlink keeps Unix sockets, broker leases, and runtime tokens on the local filesystem (0700), because Drive FUSE cannot bind Unix sockets.

Model auth lives inside the persisted `~/.omp` state from the user's own login/setup. `config.yml` holds routing only — the active default is `nvidia/minimaxai/minimax-m3.1-flash` (NVIDIA).

## Env

`FIRECRAWL_API_KEY` (web search) and `NVIDIA_API_KEY` (NVIDIA provider) exported by the lifecycle hook from Drive key files (both verified live). Note: omp expects `NVIDIA_API_KEY`, **not** `NVIDIA_NIM_API_KEY`.

## Lifecycle hook

`apps/oh-my-pi.sh` hardens the runtime wiring:

- `/etc/profile.d/omp-web.sh` is written **atomically** (temp file + `mv`, mode `0600`, owner `root:root`)
- Drive key files (`firecrawl.key`, `nvidia.key`) are `chmod 0600`
- `$HOME_OMP/omp/run` is mode `0700` (and `/root/.omp` is tightened to `0700` as well)
- The hook **exits 1** if `omp` is missing from PATH or if `omp --version` fails — a broken install fails the hook instead of silently passing

## Type

`tool` — no daemon; auto-generated shell wrapper in `/etc/profile.d/colabos.sh` detects updates and calls `svc snapshot oh-my-pi`. The lifecycle hook refreshes the persisted `run/` dirs and checks `omp --version`.

## Reclaim safety

Simulated: `rm /opt/colabos/oh-my-pi; svc install oh-my-pi; doctor` → ALL CHECKS PASSED, sessions + auth preserved via Drive, `omp -p` OK with no env.

## Troubleshooting

- `omp: command not found` → `source /etc/profile.d/colabos.sh`, then `svc doctor --fix`.
- `No models available` → re-run provider login/setup (auth lives in `~/.omp` state); check `svc doctor` persist symlink.
- Upgrade: source `/etc/profile.d/colabos.sh`, run `omp update --check`, then `omp update`; the wrapper snapshots and reconciles the updated binary automatically.

## Current retention and verification

- Current: `oh-my-pi-19.0.1-f93076d1a2cb38dc.tar.zst`.
- Prior: `oh-my-pi-19.0.0-50bcf07c7b4b65f1.tar.zst`.
- `omp update --check` reports 19.0.1 current after the upgrade.
- Provider smoke, simulated cold restore, warm boot, and full doctor passed.

## Local daemon runtime and SQLite database isolation

1. **Daemon IPC:** The lifecycle hook recreates `/run/omp-runtime` mode 0700 and enforces `~/.omp/run -> /run/omp-runtime` on every boot. This prevents the text-prediction and project brokers from attempting unsupported Unix-socket binds inside Drive FUSE.
2. **SQLite Database Isolation:** Drive `agent/` is bind-mounted to `/run/omp-agent-drive`, the 4 SQLite DBs are staged as real local files in `/run/omp-db` (mode 0700) with local passthrough symlinks for non-DB entries (`config.yml`, `models.yml`, `sessions/`, etc.), and `/run/omp-db` is directory-bind-mounted onto `~/.omp/agent/`. No symlinks are stored on Drive FUSE, and all `.db`, `-wal`, and `-shm` files stay 100% local.
3. **Atomic Sync (`omp-db-sync`):** `/usr/local/bin/omp-db-sync` uses SQLite's native backup API with `PRAGMA quick_check;` integrity verification via a periodic background daemon (`--daemon --interval 60`, dirty-only) and a shell `EXIT` trap in `/run/omp-runtime/env.sh` to flush snapshots back to `home/oh-my-pi/omp/db_store/`.
