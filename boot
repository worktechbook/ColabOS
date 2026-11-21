#!/usr/bin/env bash
# ColabOS Boot - instant-on like laptop
#
# Preconditions checked before the engine is allowed to run:
#   0. Running as root (engine installs to /opt and /usr/local/bin)
#   1. $DRIVE is actually mounted as a Drive FUSE mount and responsive
#   2. the ColabOS tree is present and non-empty
#   3. the engine and the app manifests are readable
#   4. required toolchain (python3, tar, flock, timeout, zstd) is available
set -euo pipefail

DRIVE="${COLABOS_DRIVE:-/content/drive}"
BASE="${COLABOS_BASE:-$DRIVE/MyDrive/ColabOS}"

fail() { echo "ERROR: $*" >&2; exit 1; }

# 0. Root check first (avoids misleading FUSE errors on permission denied).
[ "$(id -u)" = "0" ] || fail "ColabOS must boot as root (the engine installs to /opt and /usr/local/bin)"

# 1. Drive mount check.
if ! mountpoint -q "$DRIVE" 2>/dev/null; then
  fail "$DRIVE is not mounted. Mount Google Drive, then re-run boot."
fi
if ! awk -v p="$DRIVE" '$2 == p && ($3 == "fuse.drive" || $3 ~ /^fuse\.drive/ || $3 ~ /^fuse\./) {found=1} END {exit !found}' /proc/mounts 2>/dev/null; then
  fail "$DRIVE is mounted but is not a Drive FUSE mount; refusing to treat it as durable disk."
fi

# 1b. Drive FUSE responsiveness canary on mount root (distinguishes timeout=124 from missing files).
rc=0
timeout 2 stat "$DRIVE/MyDrive" >/dev/null 2>&1 || rc=$?
if [ "$rc" -eq 124 ]; then
  fail "Google Drive FUSE is mounted but unresponsive (canary timed out). Remount Drive and re-run boot."
elif [ "$rc" -ne 0 ]; then
  fail "Google Drive mount at $DRIVE/MyDrive is not accessible (stat exited $rc). Remount Drive and re-run boot."
fi

# 2. ColabOS tree present.
[ -d "$BASE" ] || fail "ColabOS tree not found at $BASE. Mount the Drive and re-run boot."

# 3. Required files readable.
[ -r "$BASE/engine/svc" ] || fail "engine not found or unreadable: $BASE/engine/svc"
[ -d "$BASE/apps" ]       || fail "app manifests directory missing: $BASE/apps"
shopt -s nullglob
manifest_files=("$BASE/apps"/*.toml)
shopt -u nullglob
MANIFESTS="${#manifest_files[@]}"
[ "$MANIFESTS" -gt 0 ]    || fail "no app manifests (*.toml) found in $BASE/apps"

# 4. Toolchain.
for bin in python3 tar flock timeout; do
  command -v "$bin" >/dev/null 2>&1 || fail "$bin is required but not installed"
done
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  echo "[boot] WARN: Python < 3.11 detected; engine will use fallback TOML parser" >&2
fi
if ! command -v zstd >/dev/null 2>&1; then
  echo "[boot] installing zstd (required to unpack app artifacts)"
  DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=60 update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=60 install -y -qq zstd \
    || fail "failed to install zstd; install it manually and re-run boot"
fi

echo "[boot] preconditions OK (drive mounted, $MANIFESTS manifests, toolchain present)"
exec python3 "$BASE/engine/svc" bootstrap
