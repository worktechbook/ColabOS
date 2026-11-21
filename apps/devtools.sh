#!/usr/bin/env bash
# devtools lifecycle hook - wire the Rust toolchain to persistent state.
set -euo pipefail

BASE="${COLABOS_BASE:-/content/drive/MyDrive/ColabOS}"
HOME_DEVTOOLS="$BASE/home/devtools"
RUSTUP_HOME_PERSIST="$HOME_DEVTOOLS/rustup"
ARTIFACT_ROOT="/opt/colabos/devtools"
ARTIFACT_RUSTUP="$ARTIFACT_ROOT/rustup"

echo "[devtools] setup start"

if [ ! -d "$ARTIFACT_RUSTUP/toolchains" ]; then
  echo "[devtools] ERROR: no Rust toolchain in $ARTIFACT_RUSTUP" >&2
  exit 1
fi

mkdir -p "$RUSTUP_HOME_PERSIST/toolchains"
chmod 700 "$RUSTUP_HOME_PERSIST" 2>/dev/null || true

# Prune broken symlinks left behind by older artifact upgrades.
for old in "$RUSTUP_HOME_PERSIST/toolchains"/*; do
  if [ -L "$old" ] && [ ! -e "$old" ]; then
    target="$(readlink "$old" 2>/dev/null || true)"
    if [[ "$target" == "$ARTIFACT_RUSTUP/toolchains/"* ]]; then
      echo "[devtools] pruning stale toolchain link: $(basename "$old")"
      rm -f "$old"
    fi
  fi
done

# Link every toolchain from the artifact into the persistent rustup home.
default_tc=""
for tc in "$ARTIFACT_RUSTUP/toolchains"/*; do
  [ -d "$tc" ] || continue
  name="$(basename "$tc")"
  default_tc="${default_tc:-$name}"
  dest="$RUSTUP_HOME_PERSIST/toolchains/$name"
  if [ -L "$dest" ]; then
    if [ "$(readlink "$dest")" != "$ARTIFACT_RUSTUP/toolchains/$name" ]; then
      ln -sfn "$ARTIFACT_RUSTUP/toolchains/$name" "$dest"
    fi
  elif [ -e "$dest" ]; then
    echo "[devtools] replacing on-Drive toolchain $name with a link to the artifact"
    rm -rf "$dest"
    ln -sfn "$ARTIFACT_RUSTUP/toolchains/$name" "$dest"
  else
    ln -sfn "$ARTIFACT_RUSTUP/toolchains/$name" "$dest"
  fi
done

if [ -z "$default_tc" ]; then
  echo "[devtools] ERROR: no toolchain directories found in $ARTIFACT_RUSTUP/toolchains" >&2
  exit 1
fi
if [[ ! "$default_tc" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "[devtools] ERROR: unexpected toolchain name: $default_tc" >&2
  exit 1
fi

# Check whether settings.toml is missing, empty, or points to a removed toolchain.
settings_file="$RUSTUP_HOME_PERSIST/settings.toml"
need_settings=0
if [ ! -s "$settings_file" ]; then
  need_settings=1
else
  cur_tc="$(sed -n 's/^[[:space:]]*default_toolchain[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$settings_file" | head -n 1 || true)"
  if [ -z "$cur_tc" ] || [ ! -e "$RUSTUP_HOME_PERSIST/toolchains/$cur_tc" ]; then
    echo "[devtools] updating stale default_toolchain (${cur_tc:-empty} -> $default_tc)"
    need_settings=1
  fi
fi

if [ "$need_settings" -eq 1 ]; then
  tmp_settings="$(mktemp "$RUSTUP_HOME_PERSIST/.settings.toml.tmp.XXXXXX")"
  trap 'rm -f "$tmp_settings"' EXIT
  {
    echo 'version = "12"'
    echo "default_toolchain = \"$default_tc\""
    echo 'profile = "minimal"'
    echo
    echo '[overrides]'
  } > "$tmp_settings"
  chmod 600 "$tmp_settings" 2>/dev/null || true
  mv -f "$tmp_settings" "$settings_file"
  trap - EXIT
fi

echo "[devtools] rustup home -> $RUSTUP_HOME_PERSIST"
echo "[devtools] toolchains:"
ls -1 "$RUSTUP_HOME_PERSIST/toolchains" 2>/dev/null | sed 's/^/[devtools]   /' || true
echo "[devtools] done"
