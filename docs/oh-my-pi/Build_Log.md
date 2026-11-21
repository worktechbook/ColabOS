# oh-my-pi - Build Log

## V18.1.11 — Initial ColabOS Release
- **Date:** 2026-09-06
- **Version:** 18.1.11 (matches `omp --version`, prebuilt `omp-linux-x64` v18.1.11)
- **Artifact:** `oh-my-pi-18.1.11-b4066b611e4a93d3.tar.zst` — 116.6 MiB (191M binary, zstd -6)
- **Bins (1):** `omp`
- **Build commands:**
  ```bash
  bash omp-install.sh --binary          # -> /root/.local/bin/omp (191M, v18.1.11)
  mkdir -p /tmp/stage_omp/bin
  cp /root/.local/bin/omp /tmp/stage_omp/bin/omp
  HASH=$(tar --sort=name -cf - -C /tmp/stage_omp . | sha256sum | cut -c1-16)
  # HASH=b4066b611e4a93d3
  tar -I 'zstd -6 -T0' -cf apps/oh-my-pi-18.1.11-${HASH}.tar.zst -C /tmp/stage_omp .
  ```
- **Hash (deterministic):** `b4066b611e4a93d3`
- **Plain setup (pre-persist):** local-only binary install, no Drive. User configured provider themselves (`~/.omp/agent/config.yml` pins default `opencode-zen/muse-spark-1.3-contributor-free`, auth inside `~/.omp` state).
- **Live test (pre-persist):** `omp models opencode-zen` → 95 models; `omp -p --model opencode-zen/muse-spark-1.3-contributor-free "say OK in 3 words"` → 3-word OK reply, exit 0.
- **Persist migration:** `cp -a /root/.omp/. home/oh-my-pi/omp/` (`run/`+`logs/` excluded), `svc install` rescued live `~/.omp` to `.bak-*` (`run/daemons`-only diff), symlinked, removed bak + stage.
- **Post-persist test:** `/usr/local/bin/omp -p ... "say PERSIST-OK in 2 words"` → `PERSIST-OK confirmed` with no env (auth from persisted state); reclaim sim `rm /opt/colabos/oh-my-pi; svc install oh-my-pi` → healthy.
- **Hook:** `apps/oh-my-pi.sh` refreshes `run/` dirs, checks `omp --version`. No secrets in hook or artifact.
- **Doctor:** ALL CHECKS PASSED (Healthy).

## V18.1.15 — Native-update + auto-snapshot
- **Date:** 2026-09-09
- **Trigger:** `omp update --check` showed 18.1.15; native `omp update` downloaded + verified + installed.
- **Auto-snapshot:** wrapper detected `update` verb, ran `svc snapshot oh-my-pi` (116.8 MiB, ~7 s), pruned old tarball (keep-1). Version bumped via `svc snapshot oh-my-pi --version 18.1.15`, then `svc install oh-my-pi`.
- **Artifact:** `oh-my-pi-18.1.15-288f965c71d3174a.tar.zst` — 116.8 MiB (200M binary).
- **Hash (deterministic):** `288f965c71d3174a`
- **Doctor:** ALL CHECKS PASSED (Healthy).

## V18.1.16 — Native-update + auto-snapshot
- **Date:** 2026-09-10
- **Trigger:** `omp update --check` showed 18.1.16; native `omp update` downloaded + verified + installed.
- **Auto-snapshot:** wrapper ran `svc snapshot oh-my-pi` (116.7 MiB, ~5 s), pruned old tarball (keep-1). Version bumped via `svc snapshot oh-my-pi --version 18.1.16`, then `svc install oh-my-pi`.
- **Artifact:** `oh-my-pi-18.1.16-fbda40efb5eb8316.tar.zst` — 116.7 MiB.
- **Hash (deterministic):** `fbda40efb5eb8316`
- **Doctor:** ALL CHECKS PASSED (Healthy).

## V18.1.17 — Native-update + auto-snapshot
- **Date:** 2026-09-11
- **Trigger:** `omp update --check` showed 18.1.17; native `omp update` downloaded + verified + installed.
- **Auto-snapshot:** wrapper ran `svc snapshot oh-my-pi` (116.7 MiB, ~5 s), pruned old tarball (keep-1). Version bumped via `svc snapshot oh-my-pi --version 18.1.17`, then `svc install oh-my-pi`.
- **Artifact:** `oh-my-pi-18.1.17-03988c69641dd7b6.tar.zst` — 116.7 MiB.
- **Hash (deterministic):** `03988c69641dd7b6`
- **Doctor:** ALL CHECKS PASSED (Healthy).

## V18.4.3 — Native update; Zen free tier gated out, NVIDIA added
- **Date:** 2026-09-29
- `omp update` → 18.4.3 (auto-snapshot fired, version bumped, reinstalled; hash `5aea3f251d8f772d`, 150.3 MiB).
- **Provider change:** Zen free tier now rejects non-OpenCode clients (`403 free tier can only be used from within OpenCode`) on every free model; paid models report `Model access is disabled` on this key. The key itself is valid — `opencode` still uses it.
- **Fix:** NVIDIA NIM added. omp expects `NVIDIA_API_KEY` (not `NVIDIA_NIM_API_KEY`); key stored at `home/oh-my-pi/nvidia.key` (600) and wired by the hook into `/etc/profile.d/omp-web.sh`. Default model in `~/.omp/agent/config.yml` → `nvidia/z-ai/glm-5.3` (verified). 170 NVIDIA models visible; many catalog entries are EOL (410) — prefer `z-ai/glm-5.3`.

## V18.4.10 — Native update + auto-snapshot
- **Date:** 2026-09-29
- `omp update` → 18.4.10; wrapper auto-snapshotted (~17 s), version bumped, reinstalled.
- Artifact: `oh-my-pi-18.4.10-193513187918dfe5.tar.zst` — 152.4 MiB. Hash `193513187918dfe5`.
- Verified live on the NVIDIA default (`nvidia/z-ai/glm-5.3`). Doctor: ALL CHECKS PASSED.

## V18.4.10 — current model routing
- **Date:** 2026-10-17
- Live default model is `nvidia/moonshotai/kimi-k3:max`; the earlier GLM 5.3 entries above are retained as historical build records.
- Runtime health uses `omp --version` and does not consume provider quota.

## V18.11.3 — Native update; dead default model caught
- **Date:** 2026-09-29
- `omp update` → 18.11.3; auto-snapshot fired, version bumped, reinstalled.
- Artifact: `oh-my-pi-18.11.3-6a951efffaff46f2.tar.zst` — 136.6 MiB. Hash `6a951efffaff46f2`.
- **Finding:** user-set default `nvidia/moonshotai/kimi-k3` was retired upstream (HTTP 410 EOL). Reverted default to `nvidia/z-ai/glm-5.3` after user approval; verified live. `web: web/firecrawl` left as-is.
- Doctor: ALL CHECKS PASSED.

## 2026-10-17 - OpenCode Zen removed
- Zen key had expired (`401 api_key_expired`) and its pinned `muse-spark-1.3-contributor-free`
  model was deprecated upstream (`410 ModelDeprecated`), so it could no longer serve requests.
- Removed completely: the stored `opencode-zen` credential in `~/.omp/agent/agent.db`
  (`omp auth-broker logout` only soft-deletes, so the row was hard-deleted, the DB VACUUMed and
  the WAL truncated to purge the key bytes), plus the stale `omp models opencode-zen` doc line.
- NVIDIA (`NVIDIA_API_KEY`) remains the only model provider; Firecrawl remains for web search.
- Verified: no Zen key bytes anywhere under `~/.omp` or Drive; omp 18.11.3 answers on
  `nvidia/z-ai/glm-5.3`.

## 2026-10-17 - 9Router custom provider added
- `~/.omp/agent/models.yml` registers provider `ninerouter` against the 9router OpenAI-compatible
  endpoint with `discovery.type = openai-models-list`, so omp enumerates models live instead of
  hardcoding them (798 discovered, including the 6 free `oc/*` models).
- Verified end-to-end: `omp models ninerouter` lists the catalog and
  `omp -p --model ninerouter/oc/space-bunny-free` returns a valid completion.
- Two constraints found while wiring it: omp rejects a loopback `baseUrl` (127.0.0.1) even though
  9router runs on this host, so the public Funnel URL is required; and `apiKey` is not env-expanded,
  so the key is stored literally in the 600-perm file (which persists to Drive with `~/.omp`).

## 2026-10-17 - 9router scoped to six models (discovery off)
- Audited omp's discovered metadata against 9router's catalog: of 798 models, only 1 matched
  exactly, 369 differed by unit convention alone (<6%), 4 had no upstream data, and **424 were
  materially wrong** — omp's `openai-models-list` discovery consumes only `id` and fills
  contextWindow/maxTokens from its own bundled registry.
- Response: removed the `discovery` block so the full catalog is no longer exposed, and pinned
  explicit entries for the six `oc/*` free models only. `oc/jev-1.13-free` was the notable
  correction (omp 128K/33K -> 9router's true 200K/64K).
- Verified: `omp models ninerouter` returns exactly 6, live completion succeeds, NVIDIA (178)
  and the default model are unaffected. Re-enabling instructions are in the models.yml comments.

## 2026-10-17 - Full capability metadata pinned for the six
- Replaced limit-only pins with complete capability records: `contextWindow`, `maxTokens`,
  `reasoning`, `input` (modalities) and per-model `thinking.efforts` ladders.
- Values cross-checked against the OpenCode Zen free-model catalogue, pi-freeflow's model
  table, the orcarouter Beam 1.0 writeup, 9router's own `capabilities` block, and omp's cached
  opencode-zen records. Corrected versus the earlier limit-only pins: beam-free 131K/34K ->
  1M/131K, deepseek-v4.1 1M/393K -> 1M/384K, mimo 205K/33K -> 1M/131K, space-bunny 537K -> 524K.
- Verified omp honours `reasoning`, `input` and `thinking.efforts` (images column tracks the
  declared modalities; per-model ladders render correctly) and that completions still work.

## V18.12.1 — Native update
- **Date:** 2026-10-18
- `omp update` → 18.12.1. Downloaded a 59.0 MB patch from 18.11.3 and verified
  sha256 `16181401e616d7d895bae31fa97476f1513d4080807d60d3a1a04006191a1bb3` before install.
- Re-staged `bin/omp`, repackaged deterministically, hash `51077e745596fc4b`.
- Artifact: `oh-my-pi-18.12.1-51077e745596fc4b.tar.zst` — 136.7 MiB.
- **Note on the native updater in ColabOS:** `omp update` writes into the extracted store
  (`/opt/colabos/store/<app>-<ver>-<hash>/bin/omp`), *not* the Drive artifact. The version-named
  store dir then holds a newer binary than its own name implies, which breaks the doctor hash
  check. Always re-stage → repackage → bump TOML → `svc install` after a native update.
- Persisted state (`/root/.omp`) untouched: the six-model `ninerouter` provider still resolves and
  `nvidia/z-ai/glm-5.3` remains the default. Verified live → `OMP-UPD-OK`.

## 2026-10-28 — Experiential Labs removed entirely; default model is direct NVIDIA
- **Finding:** the 9router combo `glm-5.3` pointed at `xlp/glm-5.3-uncensored:free`
  (Experiential Labs, `https://api.experientiallabs.ai/v1`). Experiential withdrew every
  `:free` alias — the upstream returns HTTP 403 `model_not_granted` for all of them — so the
  combo could not serve a single request. The provider's own connection was already marked
  `testStatus: unavailable`.
- **Decision (user):** remove Experiential Labs completely — provider, models, combo and key —
  rather than repoint the combo. The direct NVIDIA model `nvidia/z-ai/glm-5.3` is the supported
  path and was already configured.
- **Removed from 9router's SQLite:** the `providerNodes` row (`Experimentallab`, prefix `xlp`),
  its `providerConnections` row (the `xpl_…` API key), the `glm-5.3` combo, the provider's
  `customModels` capability rows, and 277 `usageHistory` rows. `glm-5.3` was also dropped from
  the `colabos-public` key's `access.allow` list, and the provider was stripped from
  `usageDaily.byProvider`. `VACUUM` cleared the freelist pages that still held the key bytes.
- **Key scrubbed everywhere:** the 4 backup snapshots that still carried the Experiential key
  were rewritten in place (they are valid restore points and would otherwise reintroduce the
  provider), `VACUUM`ed, and re-validated with `PRAGMA integrity_check`. The key was also
  redacted from the local omp session transcript and its bash log.
- **omp config:** dropped the `glm-5.3` override from `models.yml` and set
  `modelRoles.default` to `nvidia/z-ai/glm-5.3:high` — the direct NVIDIA model.
- **Docs corrected:** the oh-my-pi User Manual still described the pre-2026-10-17 state —
  "exactly six free `oc/*` models", "discovery deliberately off", and a six-row model table.
  Reality is discovery **on**, scoped by the 9router key's `access.allow` list, which now
  allows `minimax-m3.1-flash` only, so `omp models ninerouter` lists exactly one model.
  Manual and README updated to match.
- **Verified live:** `omp models ninerouter` → 1 model with the pinned limits; 9router
  `/v1/models` advertises only `minimax-m3.1-flash`; 9router `PRAGMA integrity_check` = ok;
  `omp -p --no-session "Reply with exactly: OK"` through the new default returns `OK`;
  `svc doctor` green; engine selftest 69/69.

## 2026-10-28 — Default switched to MiniMax M3.1 Flash; prompt-history warning fixed
- **Trigger:** NVIDIA retired `z-ai/glm-5.3` at 08:00:00Z on 2026-10-28 — the endpoint returns
  HTTP 410 `The model 'z-ai/glm-5.3' has reached its end of life`. The default set earlier the
  same day was already dead. Other NVIDIA GLM aliases are also retired
  (`z-ai/glm-5.2` EOL 2026-08-21, `moonshotai/kimi-k2-thinking` EOL 2026-05-12,
  `openai/gpt-oss-120b` EOL 2026-09-03).
- **Decision (user):** switch the default to **MiniMax M3.1 Flash**, i.e. the 9router combo
  `ninerouter/minimax-m3.1-flash:high`, which resolves to
  `nvidia/minimaxai/minimax-m3.1-flash` and is the one model the `colabos-public` key
  allows.
- **omp config:** `modelRoles.default` in `config.yml` → `ninerouter/minimax-m3.1-flash:high`.
  The stale `models.yml` comment pointing at the retired NVIDIA model was corrected.
- **Prompt-history warning — root cause:** `HistoryStorage add failed: SQLiteError: database
  disk image is malformed` (omp log, pid 8651, 08:04:38Z and 08:05:23Z). This was fallout from
  the earlier `history.db` rebuild: the FTS5 external-content index was left inconsistent with
  the `history` table, so inserts that fired the `history_ai` trigger failed. A plain
  `PRAGMA integrity_check` still reported `ok` because the corruption was in the FTS index,
  not the main b-trees.
- **Fix:** rebuilt the FTS index (`INSERT INTO history_fts(history_fts) VALUES('rebuild')`) and
  checkpointed the WAL. `history` and `history_fts` rowids now match exactly (61/61 at the
  time), and `PRAGMA integrity_check` = ok.
- **Verified live:** a detached interactive omp instance was started, a prompt was typed and
  submitted, and it was read back from `history.db` (row 62) — no warning, no new
  `HistoryStorage` errors. The interactive header shows
  `MiniMax M3.1 Flash [NVIDIA NIM]`. `omp -p --no-session` through the new default returns
  `OK`; `svc doctor` green; engine selftest 69/69.
- **Key hygiene:** the Experiential credential was confirmed absent from every credential
  context on the system — 0 full credentials and 0 prefix mentions. The remaining
  `experientiallabs` string sites carry no secret: the user's own original prompt in
  `history.db` and the session transcript, the local bash log, the 9router access log, and the
  removal records in these docs.

## V18.13.3 - Update (2026-10-31)
- **Version:** 18.13.3 (artifact `oh-my-pi-18.13.3-4628e39b83fa3418.tar.zst`, 148 MiB, sha256 `ab12b5d78dc73bacbb4da8c1f796e84a2ed4a93280e6d015916c67daf13f84dc`).
- **Verification:** `omp --version` -> 18.13.3; `omp models ninerouter` -> 1 model; bare `omp -p` smoke passed after `enabledModels` set to `ninerouter/minimax-m3.1-flash`.

## 2026-10-31 - 9Router removed
- 9Router service, persisted state, secrets, backups, artifacts, hooks, and docs removed.
- omp no longer has a `ninerouter` provider; `models.yml` removed.
- Default switched to `nvidia/minimaxai/minimax-m3.1-flash`; `enabledModels` updated.
- Verified: `omp --version`, bare `omp -p` smoke, and `omp models` (NVIDIA) pass.

## Update (2026-10-31)
- Native update on the 18.14.x line (151 MiB artifact).
- **Verification:** `omp --version` matched the shipped version; bare `omp -p` smoke passed.
- Superseded by the v18.16.0 artifact recorded below.

## V18.16.0 — ColabOS v1.1.7 remediation pass (2026-11-09)
- **Version:** 18.16.0 (artifact `oh-my-pi-18.16.0-5ba96a1be717c961.tar.zst`, 150 MiB,
  sha256 `0aa7ae957fb8e4a8064d367dac0497835d763dc66e57c8aab9fd23cedde8694a`).
- **Version bump:** to 18.16.0; deterministic re-pack hash `5ba96a1be717c961`.
- **Persisted-files list corrected:** `home/oh-my-pi/nvidia.key` (mode 600, NVIDIA provider key on Drive)
  was missing from the documented list and is now recorded alongside `firecrawl.key`.
- **Hook hardening (`apps/oh-my-pi.sh`):**
  - `/etc/profile.d/omp-web.sh` is written atomically (temp file + `mv`), mode `0600`, owner `root:root`
  - Drive key files (`firecrawl.key`, `nvidia.key`) are `chmod 0600`
  - `$HOME_OMP/omp/run` is mode `0700`
  - The hook exits `1` if `omp` is missing from PATH or `omp --version` fails
- **Doc correction:** the old "ephemeral `run/` dir" claim was wrong — `/root/.omp` is a Drive symlink,
  so `run/` **is persisted** (and mode-hardened by the hook).

## V18.18.3 — Version-drift remediation

- Updated from 18.16.0 to 18.18.3.
- Artifact: `oh-my-pi-18.18.3-da3ef62070e88bfd.tar.zst` — 164,110,896 bytes.
- SHA-256: `67254f07faad1b7724fc426c4843075d78e7b3d83611b3b43b6516189a07edca`.
- Added `[artifact].version_bin = "omp"`; snapshot now takes the version from the updated binary rather than preserving a stale manifest version.

## V18.18.6 — Superseded

- Native update 18.18.3 → 18.18.6; patch verified by OMP before installation.
- Artifact: `oh-my-pi-18.18.6-340eb101c8cef6a7.tar.zst` — 164,161,127 bytes (156.6 MiB).
- Deterministic tree hash: `340eb101c8cef6a7`.
- SHA-256: `c072df1ee62d7d0b554cbe521b7d40b7e9c1c6e3cec68a739e1bb95d56c4f3df`.
- Current-plus-prior retention: 18.18.6 current, 18.18.3 prior.
- Verified: artifact digest, extracted-tree hash, `omp --version`, provider smoke, cold restore, warm boot, and full doctor.
- State hygiene: credential literals were atomically redacted from the persisted audit transcript; stale daemon clients/provider-inflight state was removed; the leaked runtime broker token was invalidated by deleting dead daemon state.

## 2026-11-14 — Experiential Labs re-added directly to OMP

This current entry supersedes the historical 2026-10-28 removal decision for the former 9Router-backed Experiential route. The user explicitly authorized a fresh direct OMP integration.

- Direct preflight to the OpenAI-compatible chat-completions endpoint succeeded with HTTP 200 using `claude-fable-5.2:free`.
- Added custom OMP provider `experiential` and explicit model `claude-fable-5.2:free` (1M context, 128K maximum output, text/image input, reasoning efforts low/medium/high/xhigh/max).
- Stored the credential only at `home/oh-my-pi/experiential.key` (0600); `models.yml` refers to `EXPERIENTIAL_API_KEY` and contains no credential literal.
- Updated `apps/oh-my-pi.sh` to enforce key mode and atomically export the environment variable through `/etc/profile.d/omp-web.sh`.
- Kept the NVIDIA MiniMax default unchanged and added the Experiential selector to `enabledModels`.
- Verified `omp models experiential`, a no-tools OMP completion, and a full-tool-schema OMP completion.

## 2026-11-14 — Experiential Labs direct OMP provider removed

At the user's request, ColabOS was returned to its pre-integration provider state. The `experiential` provider block, `claude-fable-5.2:free` enabled-model selector, lifecycle-hook export, provider profile export, and canonical key file were removed. NVIDIA MiniMax remains the unchanged default. Post-removal verification confirmed that OMP no longer lists the provider, the removed key has zero exact occurrences in ColabOS, doctor is healthy, and the engine self-test remains 112/112.

## V18.22.0 — Prior release

- Updated through `omp update`; the native patch was verified before installation and the ColabOS wrapper snapshot reconciled manifest, artifact, store, live link, and binary.
- Artifact: `oh-my-pi-18.22.0-870c2f462077a738.tar.zst` — 168,453,150 bytes (160.7 MiB).
- Deterministic tree hash: `870c2f462077a738`.
- SHA-256: `12dc5bc113751576fb2c3a636bda650304d706b13ff10907571e814e58314a7a`.
- Retention: 18.22.0 current plus 18.18.6 prior.
- Audit found the text-prediction daemon failing to bind its broker socket under Drive-backed `~/.omp/run` with ENOTSUP. A direct Unix-socket probe reproduced the failure on Drive and succeeded locally.
- Made `~/.omp/run` a lifecycle-enforced symlink to local `/run/omp-runtime` mode 0700, covering daemon brokers and tiny-model worker sockets. Removed dead persisted IPC residue and three broken Chromium singleton symlinks after confirming no OMP or Chrome process was active.

## V18.22.2 — Prior release (2026-11-18)

- Updated via native `omp update` from 18.22.0 to 18.22.2 (72.8 MB patch verified with SHA-256 `80a692c5adb9c71124bb11e77bd7edb3cf8fbbab6980db3206dcb6a4cb2905b5`).
- Automatic wrapper snapshot intercepted the update verb and reconciled manifest, artifact, store, live link, and binary.
- Artifact: `oh-my-pi-18.22.2-5b0e727d424f8f96.tar.zst` — 169,214,030 bytes (161.4 MiB).
- Deterministic tree hash: `5b0e727d424f8f96`.
- SHA-256: `3a61eda090edc7e09ea956a940f5d54db5ff5bbd2a8ec7d983ae4159508fe51c`.
- Retention: 18.22.2 current plus 18.22.0 prior (pruned 18.18.6).
- Verification: `omp --version` -> 18.22.2, `svc doctor` healthy, engine self-test 112/112 passed.

## V19.0.0 — Major release (2026-11-19)

- Updated via native `omp update` from 18.22.2 to 19.0.0 (77.6 MB patch verified with SHA-256 `c7cc5c8d505053c8ffaf180417e5d5c781235b9d936f286810560151120109bf`).
- Automatic wrapper snapshot intercepted the update verb and reconciled manifest, artifact, store, live link, and binary.
- Artifact: `oh-my-pi-19.0.0-50bcf07c7b4b65f1.tar.zst` — 172,641,375 bytes (164.6 MiB).
- Deterministic tree hash: `50bcf07c7b4b65f1`.
- SHA-256: `944f502e1ae240fb7d4b766965dfd04cffef3a8aabec6858d41fae64a6978ba7`.
- Retention: 19.0.0 current plus 18.22.2 prior (pruned 18.22.0).
- Verification: `omp --version` -> 19.0.0, `svc doctor` ALL CHECKS PASSED (Healthy), engine self-test 112/112 passed.

## 2026-11-20 — SQLite Drive FUSE isolation and atomic sync architecture

- **Architectural Motivation:** Audit identified live SQLite operations directly on Google Drive FUSE as a primary reliability risk due to lack of standard POSIX locking semantics, WAL shared memory issues, and high write latency over FUSE.
- **Tiered Persistence Implementation:**
  - Static configuration (`config.yml`, `models.yml`), prompts, and conversation sessions (`sessions/`) persist directly on Google Drive (`home/oh-my-pi/omp/`).
  - Active runtime SQLite databases (`agent.db`, `history.db`, `models.db`, `skill-descriptions.db`) are staged locally in `/run/omp-db` (mode 0700) on local ext4/tmpfs and bind-mounted over `~/.omp/agent/` targets.
  - Created `/usr/local/bin/omp-db-sync` utility using Python's native SQLite C-level backup API (`sqlite3_backup`) and `PRAGMA quick_check;` integrity verification to flush atomic snapshots back to `home/oh-my-pi/omp/db_store/`.
  - Updated lifecycle hook `apps/oh-my-pi.sh` to automatically stage local databases, establish bind mounts, and register an exit flush trap (`trap ... EXIT INT TERM`) in `/etc/profile.d/omp-web.sh`.
- **Validation:**
  - `omp-db-sync --status` verified active bind-mount isolation and snapshot consistency.
  - Live OMP completions verified zero FUSE lock stalls.
  - `svc doctor` ALL CHECKS PASSED (Healthy); ColabOS engine self-test 112/112 passed.
  - Documentation updated across `docs/master/Architecture.md`, `docs/oh-my-pi/README.md`, and `docs/oh-my-pi/User_Manual.md`.

## 2026-11-20 - Upgrade to oh-my-pi v19.0.1 & Engine Self-Test Hardening

- **Upgrade Trigger:** Upstream release of oh-my-pi v19.0.1.
- **Native Update & Snapshot Workflow:**
  - Invoked native omp update on colabos-node (colabos-node.example-tailnet.ts.net).
  - Fetched and applied verified patch 6ceef04430851bb1050c6fda3af467412eb44a11df0a6ff8121fe601013c5415 (73.3 MB).
  - ColabOS auto-snapshot captured content tree into new artifact:
    - Artifact: oh-my-pi-19.0.1-f93076d1a2cb38dc.tar.zst (164.6 MiB / 172,600,141 bytes)
    - SHA-256 Digest: 3065ebbf4730797ea009be30c605f14292e622440be124cdabde5d37f960fd00
    - Content Hash: `f93076d1a2cb38dc`
  - Reconciled live store stem: /opt/colabos/store/oh-my-pi-19.0.1-f93076d1a2cb38dc.
  - Manifest `apps/oh-my-pi.toml` atomically updated to v19.0.1 with new digest.
  - Pruned previous secondary artifact oh-my-pi-18.22.2-5b0e727d424f8f96.tar.zst; retaining oh-my-pi-19.0.1-f93076d1a2cb38dc.tar.zst (current) and oh-my-pi-19.0.0-50bcf07c7b4b65f1.tar.zst (prior).
- **Engine v1.1.8 & Test Suite Hardening:**
  - Added svc doc-table (and svc status --markdown / svc list --markdown) to generate standardized Markdown/JSON state tables directly from live manifests, eliminating manual documentation drift.
  - Implemented failure-injection tests in engine/selftest.py:
    - `test_tampered_store_repair`: Verifies tampered store directories are caught by content-hash verification and force-healed by svc doctor --fix.
    - `test_sqlite_isolation_integrity`: Verifies omp-db-sync detects corrupted databases via PRAGMA quick_check;, aborts without clobbering persistent backups, and cleans up temporary staging files.
    - `test_doc_table`: Verifies dynamic Markdown and JSON manifest table generation.
  - Test suite grew from 112 to **130 passed tests (130/130 passing, 0 failures)**.
  - Full system verification with svc doctor confirmed: ALL CHECKS PASSED (Healthy).
## 2026-11-20 — Directory-Bind-Mount SQLite Isolation & Engine Hardening

- **Root Cause (DriveFS Symlink Flattening):** Initial single-file bind mounts left `agent/` on `fuse.drive` so SQLite `-wal`/`-shm` sidecars still landed on Drive FUSE, and `os.replace()` during restore could detach bind-mount inodes. Switching to file symlinks inside Drive (`agent/<db> -> /run/omp-db/<db>`) passed immediate dentry-cached probes, but Google Drive FUSE subsequently synced those symlinks to Drive as 20–33 byte plain text files containing the target path. On revalidation, `omp`'s `bun:sqlite` engine threw `SQLiteError: file is not a database`, triggering corruption recovery (`.corrupt-*` and `.recovery.lock`). All four canonical backups in `db_store/` remained intact (`PRAGMA quick_check;` = `ok`).
- **Directory-Bind-Mount Architecture (`home/oh-my-pi/bin/omp-db-sync`):**
  - Underlying Drive `agent/` is bind-mounted to `/run/omp-agent-drive` (direct Drive view).
  - The 4 active SQLite DBs (`agent.db`, `history.db`, `models.db`, `skill-descriptions.db`) are staged as real local files in `/run/omp-db` (mode `0700`, tmpfs/local), keeping both `.db` and `-wal`/`-shm` sidecars 100% off Drive FUSE.
  - All non-DB entries (`config.yml`, `models.yml`, `sessions/`, `blobs/`, `cache/`, `memories/`, `predict/`, etc.) are wired via **local** passthrough symlinks inside `/run/omp-db/<entry> -> /run/omp-agent-drive/<entry>` — zero symlinks are stored on Drive FUSE.
  - `/run/omp-db` is directory-bind-mounted onto `home/oh-my-pi/omp/agent`.
  - Periodic background sync (`omp-db-sync --daemon --interval 60`, dirty-only) and a shell `EXIT`-only trap (no `INT` hijack) flush verified SQLite Online Backup API snapshots (`PRAGMA quick_check;`) to `db_store/` and persist any atomically-renamed non-DB files back to `/run/omp-agent-drive/`.
- **Hook & Engine Hardening:**
  - `apps/oh-my-pi.sh`: wired `/run/omp-runtime/env.sh` into `/root/.bashrc` above `[ -z "$PS1" ] && return` so non-interactive shells receive env keys; removed `INT`/`TERM` from the shell flush trap; started the 60s `omp-db-sync` daemon.
  - `engine/svc`: reordered `cmd_doctor` so version-drift detection runs before content-hash tamper repair (preventing `--fix` from overwriting in-place native updates); added non-force repair callbacks to `app_health`/`expose_health`; added a local Unix-socket check on `/var/run/tailscale/tailscaled.sock` to the shallow warm-boot fast path.
- **Verification:** `engine/selftest.py` expanded from 137 to **145/145 passed (0 failed)**; live `omp --version` (`omp/19.0.1`), `omp models nvidia` (184 models), `omp-db-sync --status` (`IN SYNC`, zero WAL/SHM/symlinks on Drive FUSE), `svc doctor` (`ALL CHECKS PASSED (Healthy)`), and warm `boot` (`0.08s`) all passed.
