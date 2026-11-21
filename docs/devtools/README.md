# devtools v1.0.0 - README

> Curated dev toolchain for ColabOS v1.1.8. Provides a full Node/Bun/Go/Rust/Python-CLI/UNIX toolkit in ~20–40 s cold / ~0.4 s warm.

## Artifact

Current: `devtools-1.0.0-a92aed243b76f7dc.tar.zst` (~370.1 MiB) in `/content/drive/MyDrive/ColabOS/apps/`
SHA-256: `a4ba1e7448e70f61459780e01c6044bc228b6dd1583e768a13410945008a0e8b`

The 16-char hash in the filename is the deterministic re-pack hash produced with
`tar --sort=name`; the SHA-256 above is the digest of the compressed `.tar.zst` file.

## Bins (20)

`node, npm, npx, pnpm, yarn, bun, bunx, go, gofmt, rustc, cargo, rustup, uv, uvx, rg, fd, jq, fzf, tree, gh`

Installed versions (v1.0.0 bundle, v1.1.7 doc refresh):
| Tool | Version |
|---|---|
| node | v24.19.0 |
| npm | 11.17.0 |
| bun | 1.3.14 |
| go | 1.22.6 |
| cargo | 1.97.1 |
| uv | 0.12.5 |
| rg (ripgrep) | 15.2.0 |
| gh | 2.103.3 |
| fd | 8.3.1 |
| jq | 1.6 |
| fzf | 0.72 |
| tree | 2.0.2 |

`tailscale`/`tailscaled` are owned by the `tailscale-ssh` service (bins are symlinked via that service's install).

## Rust layout (v1.1.7)

The Rust toolchain stays **inside the artifact** (`/opt/colabos/devtools/rustup/toolchains/`) and
executes from local disk, never from Drive FUSE. Rustup's **mutable** state — `settings.toml`,
download cache, `tmp/`, update hashes — lives on Drive instead, so a single `rustup` invocation can
no longer rewrite the extracted tree and trip doctor's content-hash check.

- `RUSTUP_HOME=/content/drive/MyDrive/ColabOS/home/devtools/rustup` (persistent, on Drive)
- `home/devtools/rustup/toolchains/<name>` → symlink into `/opt/colabos/devtools/rustup/toolchains/<name>`
- `home/devtools/rustup/settings.toml`, `downloads/`, `tmp/`, `update-hashes/` — rustup-owned, mutable
- The `rustc`/`cargo` shims are rustup proxies (`exec -a`), so they resolve through `RUSTUP_HOME`

The artifact's `rustup/` directory contains **only** the toolchain; no mutable rustup state ships in it.
The dead `cargo/` directory that used to ship inside the artifact (279 MB of 15 identical rustup proxy
copies plus a stale `cargo/env` pointing at `/tmp/stage_devtools`) was **removed** from the artifact.

## Lifecycle hook

`apps/devtools.sh` is the devtools lifecycle hook. It links every artifact toolchain into the
persistent rustup home (stable `/opt/colabos/devtools/...` link targets, so a later `svc snapshot`
that renames the store dir cannot break them), seeds `settings.toml` if absent while preserving an
existing user configuration, and never writes inside the artifact tree.

## Persist

- `home/devtools/cargo  -> /root/.cargo` (crates registry + cargo home)
- `home/devtools/npm    -> /root/.npm`   (npm cache + logs)
- `home/devtools/gh     -> /root/.config/gh` (gh CLI auth/config)
- `home/devtools/rustup -> $RUSTUP_HOME` (rustup settings + caches; toolchain itself stays in the artifact)

## Env

`GOROOT=/opt/colabos/devtools/lib_go`, `CARGO_HOME=/root/.cargo`, `RUSTUP_HOME=/content/drive/MyDrive/ColabOS/home/devtools/rustup`

## Type

`tool` — no daemon; auto-generated shell wrappers in `/etc/profile.d/colabos.sh` detect updates and call `svc snapshot devtools`. See `docs/master/Agent.md` §4 and `docs/master/Architecture.md` §3 for engine/wrapper details.

## Snapshot

- After an update (auto-detected) or manual `svc snapshot devtools`, the live install is repacked with a fresh deterministic 16-char hash and `devtools.toml [artifact].file` is updated.
- The engine keeps the current tarball plus one prior revision (app-scoped prune).
- Wrappers are serialized via `/run/colabos/colabos_snapshot.lock` so concurrent invocations don't produce corrupt tarballs.
