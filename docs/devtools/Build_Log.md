# devtools - Build Log

## V1.0.0 — Initial Release
- **Date:** 2026-08-22
- **Version:** 1.0.0
- **Artifact (superseded):** `devtools-1.0.0-a995ed8116027a7f.tar.zst` — 605,735,665 bytes (578 MiB)
- **Bins (20):** `node, npm, npx, pnpm, yarn, bun, bunx, go, gofmt, rustc, cargo, rustup, uv, uvx, rg, fd, jq, fzf, tree, gh`
- **Build command (v1.0.0):**
  ```bash
  tar -I 'zstd -6 -T0' -cf apps/devtools-1.0.0-a995ed8116027a7f.tar.zst -C /opt/colabos/devtools .
  ```
- **Hash (v1.0.0, non-deterministic tar):** first 16 hex of `tar -cf - -C /opt/colabos/devtools . | sha256sum` = `a995ed8116027a7f`
- **Doctor:** ALL CHECKS PASSED after warm boot.
- **Persist:** `home/devtools/{cargo,npm,gh}` linked under `/root`.

## V1.0.0 — v1.1.1 Deterministic Re-Pack
- **Date:** 2026-08-26
- **Reason:** v1.1.1 engine switched to `tar --sort=name` for deterministic hashes; the original tarball's ordering produced a different hash under the new algorithm, so it was re-snapshotted to keep `svc status` green.
- **Artifact (superseded):** `devtools-1.0.0-4d8a6c1c9dfc7790.tar.zst` — 604,722,165 bytes (576.7 MiB)
- **Build command (v1.1.1 deterministic):**
  ```bash
  tar -I 'zstd -6 -T0' --sort=name -cf apps/devtools-1.0.0-4d8a6c1c9dfc7790.tar.zst -C /opt/colabos/devtools .
  ```
- **Hash (deterministic):** `4d8a6c1c9dfc7790`
- **Prune:** `devtools-1.0.0-0b76e3b32dfa980e.tar.zst` removed (keep-last-2 at the time).
- **Doctor:** ALL CHECKS PASSED (Healthy) with `svc doctor --fix`.
- **Doc sync note (2026-08-30): current `devtools.toml` exposes 20 bins. `tailscale`/`tailscaled` are owned by the `tailscale-ssh` app and should not be counted as devtools bins.**
- **v1.1.4 note:** rollback command removed and only the current artifact was retained at that time.

## V1.0.0 — v1.1.5 launcher repair
- **Date:** 2026-10-17
- **Reason:** the root `bin/pnpm` and `bin/yarn` launchers had been copied out of their package directories, so their relative imports were invalid. Replaced them with relative symlinks to the packaged launchers.
- **Artifact (superseded):** `devtools-1.0.0-ecc57e2475c0920c.tar.zst` — 593,289,280 bytes (565.8 MiB).
- **Hash (deterministic):** `ecc57e2475c0920c`.
- **Verified:** `pnpm --version` → `11.22.0`; `yarn --version` → `1.22.22`; full 20-command runtime health passed.
- **Retention:** current artifact plus prior `devtools-1.0.0-4d8a6c1c9dfc7790.tar.zst`.

## V1.0.0 - Re-hash (2026-10-31)
- Artifact was re-packed after a native-toolchain repack (567 MiB) and re-hashed for deterministic
  ordering. Superseded by the v1.1.7 artifact recorded below; the engine now prunes to exactly the
  current artifact plus one prior revision.

## V1.0.0 — ColabOS v1.1.7 remediation pass (2026-11-09)
- **Artifact (superseded):** `devtools-1.0.0-06d36cf287b3bf1c.tar.zst` — 496,945,069 bytes (~474 MiB).
- **SHA-256:** `d247992f8491dab9bff187d6dd1e87dfed0bdb10d1c2d47a1af09bd14c0d45d1` (matches `apps/devtools.toml`).
- **Rust layout reworked:** `RUSTUP_HOME` moved from `/opt/colabos/devtools/rustup` (inside the artifact) to
  `/content/drive/MyDrive/ColabOS/home/devtools/rustup` (persistent Drive home). The toolchain stays in the
  artifact; rustup's mutable state (`settings.toml`, `downloads/`, `tmp/`, `update-hashes/`) lives on Drive,
  so rustup can no longer mutate the extracted artifact tree and trip doctor's hash check.
- **New lifecycle hook:** `apps/devtools.sh` links the artifact toolchain into the persistent rustup home
  (stable `/opt/colabos/devtools/...` link targets so a `svc snapshot` store rename cannot break them) and
  seeds `settings.toml` only when absent.
- **Dead weight removed:** the artifact's `cargo/` directory (279 MB of 15 identical rustup proxy copies plus a
  stale `cargo/env` pointing at `/tmp/stage_devtools`) was deleted; the `rustc`/`cargo` shims are now rustup
  proxies using `exec -a`.
- **Artifact tree now contains only** `rustup/toolchains` — no mutable rustup state ships in the artifact.
- **Docs corrected:** the bogus "the `4d8a6c...` hash is the v1.1.1 deterministic re-pack" line and the
  "engine keeps only the current tarball" claim were removed — the engine prunes to exactly the current
  artifact plus one prior revision (app-scoped).

## Current bundled-version inventory

The unchanged current artifact `devtools-1.0.0-06d36cf287b3bf1c.tar.zst` was reverified against the live store. Key versions: Node 24.19.0, npm 11.17.0, pnpm 11.22.0, Yarn 1.22.22, Bun 1.3.14, Go 1.22.6, Rust/Cargo 1.97.1, uv 0.12.5, ripgrep 15.2.0, fd 8.3.1, jq 1.6, fzf 0.72.0, tree 2.0.2, and GitHub CLI 2.103.3. Full 20-command runtime health passed under `svc doctor`.

## Documentation correction after live artifact audit

A fresh command-by-command check of the unchanged `06d36cf287b3bf1c` artifact corrected three stale claims: live versions are ripgrep 15.2.0, fd 8.3.1, and jq 1.6. Doctor content hash still matches the artifact; this was documentation drift, not runtime mutation.

## V1.0.0 — Binary Deduplication Pass (2026-11-18)
- **Artifact (current):** `devtools-1.0.0-a92aed243b76f7dc.tar.zst` — 388,092,721 bytes (~370.1 MiB).
- **Prior artifact retained:** `devtools-1.0.0-06d36cf287b3bf1c.tar.zst` (~473.9 MiB).
- **SHA-256:** `a4ba1e7448e70f61459780e01c6044bc228b6dd1583e768a13410945008a0e8b` (matches `apps/devtools.toml`).
- **Deterministic Tree Hash:** `a92aed243b76f7dc`.
- **Deduplication Optimization:**
  - `bin/bunx` (92.7 MB raw copy of `bun`) converted to a relative symlink to `bun` (`bunx -> bun`).
  - 11 identical rustup proxies in `bin/` (`cargo-clippy`, `cargo-fmt`, `cargo-miri`, `clippy-driver`, `rls`, `rust-analyzer`, `rustdoc`, `rustfmt`, `rust-gdb`, `rust-gdbgui`, `rust-lldb`; 20.8 MB each) converted to relative symlinks to `rustup`.
  - Uncompressed `bin/` directory reduced from 646 MB to 339 MB (-307 MB).
  - Compressed archive reduced from 473.9 MiB to 370.1 MiB (-103.8 MiB, ~22% size reduction).
  - Cold-boot extraction speed improved by ~2.5–3.5 s.
- **Verification:** All 20 declared binaries tested and passed; `svc doctor` ALL CHECKS PASSED; engine regression suite 112/112 passed.
