#!/usr/bin/env bash
# oh-my-pi lifecycle hook - refresh ephemeral runtime dirs + wire web keys + SQLite isolation.
set -euo pipefail
BASE="${COLABOS_BASE:-/content/drive/MyDrive/ColabOS}"
HOME_OMP="$BASE/home/oh-my-pi"
OMP_RUNTIME="/run/omp-runtime"
ENV_FILE="$OMP_RUNTIME/env.sh"

echo "[oh-my-pi] setup start"

install -d -m 700 -o root -g root "$OMP_RUNTIME"
mkdir -p "$HOME_OMP/omp"

# Drive FUSE cannot bind Unix sockets. Keep the complete OMP run subtree local.
if [ ! -L "$HOME_OMP/omp/run" ] || [ "$(readlink "$HOME_OMP/omp/run" 2>/dev/null || true)" != "$OMP_RUNTIME" ]; then
  rm -rf "$HOME_OMP/omp/run"
  ln -s "$OMP_RUNTIME" "$HOME_OMP/omp/run"
fi
chmod 700 /root/.omp 2>/dev/null || true

# --- SQLite FUSE Isolation & Atomic Sync ---
OMP_DB_LOCAL="/run/omp-db"
install -d -m 700 -o root -g root "$OMP_DB_LOCAL"
install -d -m 700 -o root -g root "$HOME_OMP/omp/db_store"
install -d -m 700 -o root -g root "$HOME_OMP/omp/agent"
install -d -m 700 -o root -g root "$HOME_OMP/bin"

if [ -f "$HOME_OMP/bin/omp-db-sync" ]; then
  install -m 755 -o root -g root "$HOME_OMP/bin/omp-db-sync" /usr/local/bin/omp-db-sync
fi

if command -v omp-db-sync >/dev/null 2>&1; then
  omp-db-sync --restore
  echo "[oh-my-pi] sqlite fuse isolation active -> $OMP_DB_LOCAL"

  # Start periodic background flush daemon (60s, dirty-only) if not already running.
  daemon_alive=0
  if [ -s "$OMP_DB_LOCAL/.daemon.pid" ]; then
    dpid="$(cat "$OMP_DB_LOCAL/.daemon.pid" 2>/dev/null || true)"
    if [ -n "$dpid" ] && kill -0 "$dpid" 2>/dev/null; then
      dcmd="$(tr '\0' ' ' < "/proc/$dpid/cmdline" 2>/dev/null || true)"
      if [[ "$dcmd" == *"omp-db-sync"* ]]; then
        daemon_alive=1
      fi
    fi
  fi
  if [ "$daemon_alive" -eq 0 ]; then
    setsid nohup /usr/local/bin/omp-db-sync --daemon --interval 60 \
      >> /var/log/omp-db-sync.log 2>&1 < /dev/null &
    echo "[oh-my-pi] started omp-db-sync periodic daemon (60s)"
  fi
fi

# Provider + web-search keys: read once at bootstrap into a local 0600 env file
# (stripping CR/LF and avoiding Drive FUSE reads on every shell login).
umask 077
if [ -f "$HOME_OMP/firecrawl.key" ]; then
  chmod 600 "$HOME_OMP/firecrawl.key" 2>/dev/null || true
fi
if [ -f "$HOME_OMP/nvidia.key" ]; then
  chmod 600 "$HOME_OMP/nvidia.key" 2>/dev/null || true
fi

env_tmp="$(mktemp "$OMP_RUNTIME/.env.sh.tmp.XXXXXX")"
profile_tmp="$(mktemp /etc/profile.d/.omp-web.sh.tmp.XXXXXX)"
trap 'rm -f "$env_tmp" "$profile_tmp"' EXIT

: > "$env_tmp"
if [ -f "$HOME_OMP/firecrawl.key" ]; then
  fc_val="$(tr -d '\r\n' < "$HOME_OMP/firecrawl.key")"
  if [ -n "$fc_val" ]; then
    printf 'export FIRECRAWL_API_KEY=%q\n' "$fc_val" >> "$env_tmp"
  fi
  unset fc_val
fi
if [ -f "$HOME_OMP/nvidia.key" ]; then
  nv_val="$(tr -d '\r\n' < "$HOME_OMP/nvidia.key")"
  if [ -n "$nv_val" ]; then
    printf 'export NVIDIA_API_KEY=%q\n' "$nv_val" >> "$env_tmp"
  fi
  unset nv_val
fi

# Shell EXIT flush trap for SQLite databases (EXIT only; never trap INT so Ctrl+C stays normal).
printf 'trap "command -v omp-db-sync >/dev/null 2>&1 && omp-db-sync --flush >/dev/null 2>&1 || true" EXIT\n' >> "$env_tmp"

chmod 600 "$env_tmp"
chown root:root "$env_tmp"
mv -f "$env_tmp" "$ENV_FILE"

printf '[ -r "%s" ] && . "%s"\n' "$ENV_FILE" "$ENV_FILE" > "$profile_tmp"
chmod 600 "$profile_tmp"
chown root:root "$profile_tmp"
mv -f "$profile_tmp" /etc/profile.d/omp-web.sh
trap - EXIT

# Wire into /root/.bashrc ABOVE any interactive-only `[ -z "$PS1" ] && return` guard
# so non-login shells (e.g. Colab !omp, bash -c) also receive keys.
touch /root/.bashrc
python3 - "$ENV_FILE" <<'PY'
import os, pathlib, re, sys, tempfile

env_file = sys.argv[1]
rc_path = pathlib.Path("/root/.bashrc")
text = rc_path.read_text(encoding="utf-8", errors="replace") if rc_path.exists() else ""

# Strip any previous ColabOS oh-my-pi runtime env block (managed or legacy).
text = re.sub(
    r'\n?# >>> colabos oh-my-pi env >>>\n.*?# <<< colabos oh-my-pi env <<<\n?',
    '\n',
    text,
    flags=re.S,
)
text = re.sub(
    r'\n?# ColabOS oh-my-pi runtime env\n\[ -r "' + re.escape(env_file) + r'" \] && \. "' + re.escape(env_file) + r'"\n?',
    '\n',
    text,
)

block = (
    '# >>> colabos oh-my-pi env >>>\n'
    f'[ -r "{env_file}" ] && . "{env_file}"\n'
    '# <<< colabos oh-my-pi env <<<\n'
)

# Insert before the first `[ -z "$PS1" ] && return` or `case $- in` guard if present.
lines = text.splitlines(keepends=True)
insert_idx = None
for i, line in enumerate(lines):
    if re.search(r'\[\s*-z\s*"\$PS1"\s*\]\s*&&\s*return', line) or re.match(r'^\s*case\s+"?\$-"?\s+in', line):
        insert_idx = i
        break

if insert_idx is not None:
    new_text = "".join(lines[:insert_idx]) + block + "\n" + "".join(lines[insert_idx:])
else:
    new_text = block + ("\n" if text and not text.startswith("\n") else "") + text

fd, tmp = tempfile.mkstemp(prefix=".bashrc.tmp.", dir=str(rc_path.parent))
try:
    os.fchmod(fd, rc_path.stat().st_mode & 0o777 if rc_path.exists() else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(new_text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, str(rc_path))
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
PY

if [ -f "$HOME_OMP/firecrawl.key" ]; then
  echo "[oh-my-pi] firecrawl key wired -> $ENV_FILE"
fi
if [ -f "$HOME_OMP/nvidia.key" ]; then
  echo "[oh-my-pi] nvidia key wired -> $ENV_FILE"
fi
echo "[oh-my-pi] ephemeral run subtree -> $OMP_RUNTIME"

if ! command -v omp >/dev/null 2>&1; then
  echo "[oh-my-pi] ERROR: omp not found on PATH" >&2
  exit 1
fi
if ! omp --version >/dev/null 2>&1; then
  echo "[oh-my-pi] ERROR: omp --version failed" >&2
  exit 1
fi
echo "[oh-my-pi] omp ok"

echo "[oh-my-pi] done"
