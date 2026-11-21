#!/usr/bin/env bash
set -euo pipefail
BASE="${COLABOS_BASE:-/content/drive/MyDrive/ColabOS}"
HOME_SSH="$BASE/home/tailscale-ssh"
KEY_NAME="colabos_ssh"
SENTINEL="/var/run/colabos-cf-bootstrap"
SOCKS_ADDR="127.0.0.1:1055"
TAILSCALE_SOCKET="/var/run/tailscale/tailscaled.sock"
TAILSCALE_HOSTNAME="${TAILSCALE_HOSTNAME:-colabos-node}"
AUTH_KEY="${TAILSCALE_AUTHKEY:-}"

echo "[tailscale-ssh] setup start"

mkdir -p /root/.ssh /run/sshd /var/run/tailscale /var/lib/tailscale /var/log "$HOME_SSH/keys" "$HOME_SSH/tailscale" "$HOME_SSH/ssh-hostkeys"
chmod 700 /root/.ssh

NEED_APT=()
command -v sshd >/dev/null 2>&1 || NEED_APT+=(openssh-server)
if ! command -v nc >/dev/null 2>&1 || ! nc -h 2>&1 | grep -q -- '-X'; then
  NEED_APT+=(netcat-openbsd)
fi
command -v ss >/dev/null 2>&1 || NEED_APT+=(iproute2)
if [ "${#NEED_APT[@]}" -gt 0 ]; then
  echo "[tailscale-ssh] installing: ${NEED_APT[*]}"
  DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=60 update -qq
  DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=60 install -y -qq "${NEED_APT[@]}"
fi

# [single-identity] Canonical SSH identity: colabos_ssh.
# Use umask 077 + install -m 600 to eliminate TOCTOU world-readable key windows.
umask 077
if [ ! -f "$HOME_SSH/keys/$KEY_NAME" ]; then
  ssh-keygen -t ed25519 -f "$HOME_SSH/keys/$KEY_NAME" -N "" -C "$TAILSCALE_HOSTNAME" -q
  echo "[tailscale-ssh] generated canonical SSH identity"
fi
if [ ! -f "$HOME_SSH/keys/$KEY_NAME.pub" ]; then
  ssh-keygen -y -f "$HOME_SSH/keys/$KEY_NAME" > "$HOME_SSH/keys/$KEY_NAME.pub"
fi
chmod 600 "$HOME_SSH/keys/$KEY_NAME" 2>/dev/null || true
chmod 644 "$HOME_SSH/keys/$KEY_NAME.pub" 2>/dev/null || true
install -m 600 "$HOME_SSH/keys/$KEY_NAME" "/root/.ssh/$KEY_NAME"
install -m 644 "$HOME_SSH/keys/$KEY_NAME.pub" "/root/.ssh/$KEY_NAME.pub"

# Manage authorized_keys via a delimited block so other authorized keys are preserved.
pub_line="$(tr -d '\r\n' < "$HOME_SSH/keys/$KEY_NAME.pub")"
auth_tmp="$(mktemp /root/.ssh/.authorized_keys.tmp.XXXXXX)"
python3 - "$auth_tmp" "$pub_line" <<'PY'
import pathlib, re, sys
out = pathlib.Path(sys.argv[1])
pub = sys.argv[2]
src = pathlib.Path('/root/.ssh/authorized_keys')
existing = src.read_text() if src.exists() else ''
start = '# >>> colabos tailscale-ssh >>>\n'
end = '# <<< colabos tailscale-ssh <<<\n'
block = f"{start}{pub}\n{end}"
pat = re.compile(re.escape(start) + r'.*?' + re.escape(end), re.S)
if pat.search(existing):
    new_text = pat.sub(lambda _: block, existing)
else:
    lines = [l for l in existing.splitlines() if l.strip() != pub]
    prefix = ('\n'.join(lines).rstrip() + '\n\n') if lines else ''
    new_text = prefix + block
out.write_text(new_text)
PY
chmod 600 "$auth_tmp"
mv -f "$auth_tmp" /root/.ssh/authorized_keys
install -m 600 /root/.ssh/authorized_keys "$HOME_SSH/keys/authorized_keys" 2>/dev/null || cp /root/.ssh/authorized_keys "$HOME_SSH/keys/authorized_keys"

for t in ed25519 rsa; do
  if [ ! -f "$HOME_SSH/ssh-hostkeys/ssh_host_${t}_key" ]; then
    ssh-keygen -t "$t" -f "$HOME_SSH/ssh-hostkeys/ssh_host_${t}_key" -N "" -q
  fi
  if [ ! -f "$HOME_SSH/ssh-hostkeys/ssh_host_${t}_key.pub" ]; then
    ssh-keygen -y -f "$HOME_SSH/ssh-hostkeys/ssh_host_${t}_key" > "$HOME_SSH/ssh-hostkeys/ssh_host_${t}_key.pub"
  fi
  chmod 600 "$HOME_SSH/ssh-hostkeys/ssh_host_${t}_key" 2>/dev/null || true
  chmod 644 "$HOME_SSH/ssh-hostkeys/ssh_host_${t}_key.pub" 2>/dev/null || true
  install -m 600 "$HOME_SSH/ssh-hostkeys/ssh_host_${t}_key" "/etc/ssh/ssh_host_${t}_key"
  install -m 644 "$HOME_SSH/ssh-hostkeys/ssh_host_${t}_key.pub" "/etc/ssh/ssh_host_${t}_key.pub"
done
echo "[tailscale-ssh] restored hostkeys"

if [ -e "$SENTINEL" ]; then
  echo "[tailscale-ssh] sentinel present; leaving sshd_config and running sshd untouched"
  if ! ss -tln 'sport = :22' 2>/dev/null | grep -q LISTEN; then
    echo "[tailscale-ssh] WARN: sentinel present but port 22 is not listening" >&2
  fi
else
  sshd_tmp="$(mktemp /etc/ssh/.sshd_config.tmp.XXXXXX)"
  trap 'rm -f "$sshd_tmp"' EXIT
  cat > "$sshd_tmp" <<'EOF'
# Hardened base settings come first so drop-ins cannot silently re-enable passwords.
Port 22
ListenAddress 127.0.0.1
PermitRootLogin prohibit-password
PasswordAuthentication no
PubkeyAuthentication yes
KbdInteractiveAuthentication no
UsePAM yes
X11Forwarding no
AcceptEnv LANG LC_*
Subsystem sftp /usr/lib/openssh/sftp-server

Include /etc/ssh/sshd_config.d/*.conf
EOF
  chmod 644 "$sshd_tmp"
  # [sshd-validate] Validate BEFORE replacing live sshd_config.
  if ! sshd -t -f "$sshd_tmp"; then
    echo "[tailscale-ssh] ERROR: generated sshd_config is invalid; refusing to replace live config" >&2
    exit 1
  fi
  mv -f "$sshd_tmp" /etc/ssh/sshd_config
  trap - EXIT

  # [sshd-pid-verify] Locate the true listening sshd master (PPID=1 or pidfile).
  PID=""
  if [ -s /var/run/sshd.pid ]; then
    CAND="$(cat /var/run/sshd.pid 2>/dev/null || true)"
    CAND_EXE="$(readlink -f "/proc/$CAND/exe" 2>/dev/null || true)"
    if [ -n "$CAND" ] && kill -0 "$CAND" 2>/dev/null && [ "$(basename "${CAND_EXE% (deleted)}")" = "sshd" ]; then
      PID="$CAND"
    else
      echo "[tailscale-ssh] WARN: stale sshd pid file; will locate the real master"
    fi
  fi
  if [ -z "$PID" ]; then
    for CAND in $(pgrep -x sshd 2>/dev/null || true); do
      PPID_VAL="$(awk '/^PPid:/ {print $2}' "/proc/$CAND/status" 2>/dev/null || true)"
      CAND_EXE="$(readlink -f "/proc/$CAND/exe" 2>/dev/null || true)"
      if [ "$PPID_VAL" = "1" ] && [ "$(basename "${CAND_EXE% (deleted)}")" = "sshd" ]; then
        PID="$CAND"
        break
      fi
    done
  fi
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    kill -HUP "$PID"
    echo "[tailscale-ssh] sshd reloaded $PID (key-only auth)"
  else
    if ! /usr/sbin/sshd; then
      echo "[tailscale-ssh] ERROR: failed to start sshd" >&2
      exit 1
    fi
    echo "[tailscale-ssh] sshd started on 127.0.0.1:22"
  fi
  for _ in $(seq 1 20); do
    ss -tln 'sport = :22' 2>/dev/null | grep -q LISTEN && break
    sleep 0.25
  done
  if ! ss -tln 'sport = :22' 2>/dev/null | grep -q LISTEN; then
    echo "[tailscale-ssh] ERROR: sshd is not listening on port 22" >&2
    exit 1
  fi
fi

TAILSCALED_BIN="$(command -v tailscaled 2>/dev/null || true)"
TAILSCALE_BIN="$(command -v tailscale 2>/dev/null || true)"
if [ -z "$TAILSCALED_BIN" ] || [ -z "$TAILSCALE_BIN" ]; then
  echo "[tailscale-ssh] ERROR: tailscale/tailscaled not found on PATH" >&2
  exit 1
fi

# [tailscaled-restart] Inspect ALL running tailscaled PIDs and strip " (deleted)"
# so upgraded binaries are cleanly replaced instead of spawning dual daemons.
CUR_EXE="$(readlink -f "$TAILSCALED_BIN" 2>/dev/null || true)"
TS_PIDS=()
while IFS= read -r p; do
  [ -n "$p" ] && TS_PIDS+=("$p")
done < <(pgrep -x tailscaled 2>/dev/null || true)

NEED_RESTART=0
KILL_PIDS=()
if [ "${#TS_PIDS[@]}" -eq 0 ]; then
  NEED_RESTART=1
elif [ "${#TS_PIDS[@]}" -gt 1 ]; then
  echo "[tailscale-ssh] WARN: multiple tailscaled PIDs (${TS_PIDS[*]}); restarting cleanly"
  NEED_RESTART=1
  KILL_PIDS=("${TS_PIDS[@]}")
else
  TSPID="${TS_PIDS[0]}"
  TS_CMDLINE="$(tr '\0' ' ' < "/proc/$TSPID/cmdline" 2>/dev/null || true)"
  RUN_EXE="$(readlink -f "/proc/$TSPID/exe" 2>/dev/null || true)"
  RUN_EXE_CLEAN="${RUN_EXE% (deleted)}"
  TS_COMM="$(cat "/proc/$TSPID/comm" 2>/dev/null || true)"
  if [ "$(basename "$RUN_EXE_CLEAN")" != "tailscaled" ] && [ "$TS_COMM" != "tailscaled" ]; then
    echo "[tailscale-ssh] WARN: pid $TSPID is not tailscaled; starting fresh"
    NEED_RESTART=1
  elif [[ "$RUN_EXE" == *" (deleted)" ]] || ([ -n "$CUR_EXE" ] && [ "$RUN_EXE_CLEAN" != "$CUR_EXE" ]); then
    echo "[tailscale-ssh] tailscaled binary changed ($RUN_EXE -> $CUR_EXE); restarting"
    NEED_RESTART=1
    KILL_PIDS=("$TSPID")
  elif [[ "$TS_CMDLINE" != *"--state=$HOME_SSH/tailscale/tailscaled.state"* ]] || \
       [[ "$TS_CMDLINE" != *"--socket=$TAILSCALE_SOCKET"* ]]; then
    echo "[tailscale-ssh] WARN: running tailscaled has unexpected --state/--socket arguments; restarting"
    NEED_RESTART=1
    KILL_PIDS=("$TSPID")
  fi
fi

if [ "$NEED_RESTART" = "1" ] && [ "${#KILL_PIDS[@]}" -gt 0 ]; then
  for kp in "${KILL_PIDS[@]}"; do
    kill "$kp" 2>/dev/null || true
  done
  for _ in $(seq 1 20); do
    alive=0
    for kp in "${KILL_PIDS[@]}"; do
      kill -0 "$kp" 2>/dev/null && alive=1
    done
    [ "$alive" -eq 0 ] && break
    sleep 0.25
  done
  for kp in "${KILL_PIDS[@]}"; do
    kill -0 "$kp" 2>/dev/null && kill -9 "$kp" 2>/dev/null || true
  done
fi

if [ "$NEED_RESTART" = "1" ]; then
  echo "[tailscale-ssh] start tailscaled userspace"
  setsid nohup "$TAILSCALED_BIN" \
    --tun=userspace-networking \
    --socks5-server="$SOCKS_ADDR" \
    --state="$HOME_SSH/tailscale/tailscaled.state" \
    --socket="$TAILSCALE_SOCKET" \
    >> /var/log/tailscaled.log 2>&1 < /dev/null &
  # Wait on socket readiness rather than sleeping 15s on unauthenticated first login.
  for _ in $(seq 1 40); do
    [ -S "$TAILSCALE_SOCKET" ] && break
    sleep 0.25
  done
fi

if ! "$TAILSCALE_BIN" --socket="$TAILSCALE_SOCKET" status >/dev/null 2>&1; then
  if [ -n "$AUTH_KEY" ]; then
    echo "[tailscale-ssh] logging in with auth key (via file)"
    ts_auth_tmp="$(mktemp /run/ts-auth.XXXXXX)"
    trap 'rm -f "$ts_auth_tmp"' EXIT
    chmod 600 "$ts_auth_tmp"
    printf '%s' "$AUTH_KEY" > "$ts_auth_tmp"
    if ! ts_err="$("$TAILSCALE_BIN" --socket="$TAILSCALE_SOCKET" up --authkey="file:$ts_auth_tmp" --hostname="$TAILSCALE_HOSTNAME" --accept-routes --reset 2>&1)"; then
      echo "[tailscale-ssh] ERROR: tailscale up failed: $ts_err" >&2
    fi
    rm -f "$ts_auth_tmp"
    trap - EXIT
  else
    echo "[tailscale-ssh] tailscale not authenticated and TAILSCALE_AUTHKEY is empty; preserving existing state only"
  fi
fi

# [tailscale-verify] Fail loudly with captured stderr.
if ! ts_err="$("$TAILSCALE_BIN" --socket="$TAILSCALE_SOCKET" status 2>&1)"; then
  echo "[tailscale-ssh] ERROR: tailscale is not authenticated: $ts_err" >&2
  exit 1
fi
if ! ts_err="$("$TAILSCALE_BIN" --socket="$TAILSCALE_SOCKET" set --hostname="$TAILSCALE_HOSTNAME" 2>&1)"; then
  echo "[tailscale-ssh] ERROR: failed to set Tailscale hostname: $ts_err" >&2
  exit 1
fi
if ! ts_err="$("$TAILSCALE_BIN" --socket="$TAILSCALE_SOCKET" serve --bg --tcp 22 tcp://127.0.0.1:22 2>&1)"; then
  echo "[tailscale-ssh] ERROR: failed to configure tailscale serve for port 22: $ts_err" >&2
  exit 1
fi
echo "[tailscale-ssh] tailscale serve active (Private Tailnet: $TAILSCALE_HOSTNAME:22)"

TAILSCALE_SOCKET="$TAILSCALE_SOCKET" TAILSCALE_BIN="$TAILSCALE_BIN" SOCKS_ADDR="$SOCKS_ADDR" python3 - <<'PY'
import ipaddress, json, os, pathlib, re, subprocess, tempfile, time

ts_sock = os.environ['TAILSCALE_SOCKET']
ts_bin = os.environ['TAILSCALE_BIN']
socks_addr = os.environ['SOCKS_ADDR']
config_path = pathlib.Path('/root/.ssh/config')
existing = config_path.read_text() if config_path.exists() else ''
start = '# >>> colabos tailscale-ssh >>>\n'
end = '# <<< colabos tailscale-ssh <<<\n'
block_lines = [
    '# >>> colabos tailscale-ssh >>>',
    '# Managed by ColabOS tailscale-ssh. Rewritten on each bootstrap.',
]
entries = []
status_ok = False
last_error = None
# [peer-retry] A freshly started tailscaled can report an empty Peer map
# before its first netmap arrives. Do not overwrite a working SSH block.
for attempt in range(12):
    try:
        data = json.loads(subprocess.check_output(
            [ts_bin, f'--socket={ts_sock}', 'status', '--json'],
            text=True))
        if not isinstance(data, dict) or 'Peer' not in data:
            raise RuntimeError('tailscale status contained no Peer status')
        peers = data.get('Peer') or {}
        by_name = {(v.get('HostName') or ''): v for v in peers.values()}
        if by_name:
            for alias, user in [('gateway-vps', 'ubuntu')]:
                peer = by_name.get(alias)
                if not peer:
                    continue
                ips = peer.get('TailscaleIPs') or []
                ipv4 = None
                for ip in ips:
                    try:
                        ipaddress.IPv4Address(ip)
                        ipv4 = ip
                        break
                    except ValueError:
                        continue
                if ipv4:
                    entries.append((alias, ipv4, user))
            status_ok = True
            break
        last_error = RuntimeError('tailscale peer map is still empty')
    except Exception as exc:
        last_error = exc
    if attempt < 11:
        time.sleep(5)

if not status_ok:
    print(f'[tailscale-ssh] WARN: could not determine tailscale peer after retries ({last_error}); leaving existing managed SSH config block unchanged')
    raise SystemExit(0)

if entries:
    for alias, host, user in entries:
        block_lines.extend([
            f'Host {alias}',
            f'    HostName {host}',
            f'    User {user}',
            '    IdentityFile /root/.ssh/colabos_ssh',
            '    IdentitiesOnly yes',
            f'    ProxyCommand nc -X 5 -x {socks_addr} %h %p',
            '    ServerAliveInterval 30',
            '    StrictHostKeyChecking accept-new',
            '',
        ])
else:
    block_lines.append('# No preferred reverse-SSH peer is currently visible in tailscale status.')
block_lines.append('# <<< colabos tailscale-ssh <<<')
block = '\n'.join(block_lines).rstrip() + '\n'
pattern = re.compile(re.escape(start) + r'.*?' + re.escape(end), re.S)
if pattern.search(existing):
    new_text = pattern.sub(lambda _: block, existing)
else:
    new_text = existing.rstrip() + ('\n\n' if existing.strip() else '') + block

fd, tmp_name = tempfile.mkstemp(prefix='.config.tmp.', dir=str(config_path.parent))
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(new_text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_name, str(config_path))
except Exception:
    try:
        os.unlink(tmp_name)
    except OSError:
        pass
    raise
PY

echo "[tailscale-ssh] done"
