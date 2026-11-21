<!-- ColabOS v1.1.8 -->
# devtools v1.0.0 (engine v1.1.8) - User Manual

## Artifact

Current: `devtools-1.0.0-a92aed243b76f7dc.tar.zst` (~370.1 MiB) in `/content/drive/MyDrive/ColabOS/apps/`
SHA-256: `a4ba1e7448e70f61459780e01c6044bc228b6dd1583e768a13410945008a0e8b`

## Installed Versions

```
node --version   -> v24.19.0
npm  --version   -> 11.17.0
bun  --version   -> 1.3.14
go   version     -> go1.22.6
cargo --version  -> 1.97.1
uv   --version   -> 0.12.5
rg   --version   -> 15.2.0
gh   --version   -> 2.103.3
fd   --version   -> 8.3.1
jq   --version   -> 1.6
fzf  --version   -> 0.72.0
```

## Native Update (auto-snapshotted)

Use the tools normally:
```bash
npm update -g npm
cargo update
rustup update
go install golang.org/x/tools/cmd/goimports@latest
```
The auto-generated shell wrapper detects:
1. Exact verbs `update|upgrade|self-update` as argv[1] **and** no `--help/--version/--dry-run/--check` flag **and** successful exit → `[colabos] snapshot devtools`.
   `install` is **not** an update verb any more — `npm install <pkg>` no longer triggers a snapshot of the devtools artifact (~370.1 MiB).
2. A binary whose mtime changed after invocation (catches self-updaters like `rustup`) → `[colabos] auto-snapshot devtools`.
   Mtime tracking uses sub-second precision (`stat -c %.9Y`).

In non-interactive shells, load the wrappers first:
```bash
source /etc/profile.d/colabos.sh
```

Wrappers are serialized through `/run/colabos/colabos_snapshot.lock` — if two tools update in the same shell (e.g. chained `npm install && cargo install`), only one snapshot runs at a time.

To manually inspect:
```bash
ls -la /content/drive/MyDrive/ColabOS/apps/devtools-*.tar.zst
svc status devtools    # must show hash OK
```

## Persistence

Crates (`~/.cargo`), npm cache (`~/.npm`), and gh config (`~/.config/gh`) live at `home/devtools/<name>` on Drive and are symlinked into place on every boot, so installs and logins survive VM reclaim.

Rust is split in two (ColabOS v1.1.7): the **toolchain** stays inside the artifact
(`/opt/colabos/devtools/rustup/toolchains/`) and runs from local disk, while rustup's **mutable** state
(`settings.toml`, download cache, `tmp/`, update hashes) lives in the persistent Drive home
`/content/drive/MyDrive/ColabOS/home/devtools/rustup` (`RUSTUP_HOME`). The `apps/devtools.sh` lifecycle
hook links the artifact toolchain into that rustup home on every install/bootstrap, so `rustup update`
survives a reclaim and no longer mutates the artifact tree.

## Adding more tools

Add the binary name to `bins = [...]` in `/content/drive/MyDrive/ColabOS/apps/devtools.toml`, place the binary in `/opt/colabos/devtools/bin/<name>` (or any nested `bin/` directory — the engine walks up to depth 3), then run:
```bash
svc snapshot devtools
svc install devtools
```
The wrapper is regenerated automatically on the next `svc bootstrap` (which every `install` calls).
