<!-- ColabOS v1.1.8 -->
# oh-my-pi v19.0.1 (engine v1.1.8) - User Manual

## Artifact

Current: `oh-my-pi-19.0.1-f93076d1a2cb38dc.tar.zst` (164.6 MiB) in `/content/drive/MyDrive/ColabOS/apps/`
SHA-256: `3065ebbf4730797ea009be30c605f14292e622440be124cdabde5d37f960fd00`

## What it is

omp terminal agent (fork of Pi): `omp` TUI, `omp -p "task"` one-shot, `--mode rpc/acp` headless. 60+ providers, Rust core, LSP/DAP wired in. Default model pinned in `~/.omp/agent/config.yml` (`modelRoles.default`).

## Use

```bash
source /etc/profile.d/colabos.sh     # non-interactive shells only
omp                                  # TUI in project dir
omp -p --model nvidia/minimaxai/minimax-m3.1-flash "explain @README.md"
omp models                           # list all
omp models nvidia                    # NVIDIA catalog
omp setup                            # onboarding / optional deps
```

Providers: **NVIDIA** (`NVIDIA_API_KEY`) is configured; Firecrawl (`FIRECRAWL_API_KEY`)
handles web search. The former OpenCode Zen credential was removed on 2026-10-17 — its key had
expired and its pinned model was deprecated. The 9Router provider was removed on 2026-10-31.

### Removed providers

- **OpenCode Zen** — removed on 2026-10-17 (expired key, deprecated pinned model).
- **9Router** — removed on 2026-10-31 (user request); omp now uses NVIDIA directly.

## Persistence

`~/.omp` (agent.db, sessions, models.db, config, natives) lives in `home/oh-my-pi/omp` on Drive, symlinked every boot — including your provider auth, so no per-boot login. Binary executes from `/opt/colabos/oh-my-pi` (not Drive FUSE).

Because `/root/.omp` is a Drive symlink, configuration, prompts, and conversation sessions persist directly on Drive. To prevent FUSE-related performance penalties and corruption:
- **Unix Sockets:** The `~/.omp/run` subtree is a symlink to local `/run/omp-runtime` (0700) because Drive FUSE cannot host Unix sockets.
- **SQLite Databases:** Drive `agent/` is bind-mounted to `/run/omp-agent-drive`, the 4 SQLite DBs live locally in `/run/omp-db` (0700) alongside local passthrough symlinks for configs/sessions, and `/run/omp-db` is directory-bind-mounted onto `~/.omp/agent/` (zero symlinks on Drive FUSE, zero `-wal`/`-shm` on Drive FUSE). Atomic snapshots are verified and flushed to `home/oh-my-pi/omp/db_store/` by `omp-db-sync` via a 60s dirty-only background daemon and a shell `EXIT` trap.

Persisted Drive key files (never in the artifact, both mode `0600`):

- `home/oh-my-pi/firecrawl.key` → exported as `FIRECRAWL_API_KEY`
- `home/oh-my-pi/nvidia.key` → exported as `NVIDIA_API_KEY`

The hook writes `/etc/profile.d/omp-web.sh` **atomically** (temp file + `mv`, mode `0600`, owner
`root:root`) and **exits 1** if `omp` is missing from PATH or `omp --version` fails — a broken install
fails the hook loudly instead of passing silently.

## Updating

```bash
source /etc/profile.d/colabos.sh
omp update --check
omp update
svc doctor
```

Wrapper auto-snapshots on `update|upgrade|self-update` verbs or mtime change. `install` is **not** an
update verb any more, so `# npm install (superseded by native update) <pkg>` no longer triggers a snapshot.

## Troubleshooting

- No wrapper: `source /etc/profile.d/colabos.sh` or `svc install oh-my-pi`.
- `No models available`: re-run provider login/setup; auth lives in `~/.omp` state — check `svc doctor` persist symlink, `--fix` recreates.
- Lost sessions: check persist symlink for `/root/.omp`.
- Old paths `/root/.bun/bin/omp`, `/root/.local/bin/omp` are ephemeral — use `omp` on PATH (`/usr/local/bin/omp`).

The generated wrapper detects the native binary replacement, snapshots it under the version reported by `omp --version`, reconciles the live store, and retains the current plus one prior artifact.

For non-login shells, the lifecycle hook creates the local runtime directory and symlink automatically; `readlink ~/.omp/run` should report `/run/omp-runtime`.
