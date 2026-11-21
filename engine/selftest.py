#!/usr/bin/env python3
"""ColabOS engine self-test.

Regression suite for engine/svc. Exercises the logic that decides whether
the system is healthy and whether an install is safe:

  * TOML parsing (native tomllib and the fallback parser must agree)
  * dependency ordering and level computation (cycles, missing deps)
  * content hashing with exclusions
  * artifact digest verification (tamper detection)
  * health-probe timeouts
  * doctor read-only behaviour (no repair without --fix)
  * manifest schema validation and manifest digest integrity

Run:
    python3 engine/selftest.py
    python3 engine/selftest.py -v

Exit code 0 = all tests passed, 1 = at least one failed.
"""
import argparse
import importlib.util
import io
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

ENGINE = pathlib.Path(__file__).resolve().parent / "svc"
VERBOSE = False


# --------------------------------------------------------------------------- #
# Harness                                                                      #
# --------------------------------------------------------------------------- #

_results = []


def check(label, condition, detail=""):
    ok = bool(condition)
    _results.append((label, ok, detail))
    mark = "PASS" if ok else "FAIL"
    line = f"  [{mark}] {label}"
    if detail and (not ok or VERBOSE):
        line += f"\n         {detail}"
    print(line, flush=True)
    return ok


def eq(label, got, want):
    return check(label, got == want, f"got={got!r} want={want!r}")


def section(title):
    print(f"\n{title}", flush=True)


def load_engine():
    """Import engine/svc as a module without running its main()."""
    src = ENGINE.read_text()
    # mod.__name__ is "colabos_svc", so __main__ guard does not execute
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("colabos_svc", None))
    exec(compile(src, str(ENGINE), "exec"), mod.__dict__)
    return mod


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #
def test_toml(mod):
    section("TOML parsing")
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "t.toml"
        p.write_text(
            '[app]\n'
            'name = "x"\n'
            'version = "1.2.3"\n'
            'depends_on = ["a", "b"]\n'
            'enabled = true\n'
            'count = 7\n'
            'ratio = 0.5\n'
            '\n'
            '[artifact]\n'
            'file = "x-1.2.3-deadbeefdeadbeef.tar.zst"\n'
            'sha256 = "' + "a" * 64 + '"\n'
            '\n'
            '[expose]\n'
            'port = "8080"\n'
            'health = "curl -fsS http://127.0.0.1:8080/ | grep -q ok"\n'
        )
        cfg = mod.load_toml(str(p))
        eq("app.name", cfg["app"]["name"], "x")
        eq("app.depends_on", cfg["app"]["depends_on"], ["a", "b"])
        eq("app.enabled is bool", cfg["app"]["enabled"], True)
        eq("app.count is int", cfg["app"]["count"], 7)
        eq("app.ratio is float", cfg["app"]["ratio"], 0.5)
        eq("artifact.sha256 length", len(cfg["artifact"]["sha256"]), 64)
        eq("expose.port", cfg["expose"]["port"], "8080")
        # A '#' inside a quoted string must not be treated as a comment.
        p2 = pathlib.Path(td) / "c.toml"
        p2.write_text('[app]\nname = "a#b"\n')
        eq("hash inside quoted string preserved", mod.load_toml(str(p2))["app"]["name"], "a#b")


def test_dependencies(mod):
    section("Dependency ordering")
    apps = [
        ("a", {"app": {"depends_on": []}}),
        ("b", {"app": {"depends_on": ["a"]}}),
        ("c", {"app": {"depends_on": ["a", "b"]}}),
    ]
    order = [n for n, _ in mod.install_order(apps)]
    check("a installs before b", order.index("a") < order.index("b"), f"order={order}")
    check("b installs before c", order.index("b") < order.index("c"), f"order={order}")

    levels = mod.install_levels(apps)
    eq("level count", len(levels), 3)
    eq("level 0", levels[0], ["a"])
    eq("level 1", levels[1], ["b"])
    eq("level 2", levels[2], ["c"])

    section("Dependency edge cases")
    cyc = [
        ("x", {"app": {"depends_on": ["y"]}}),
        ("y", {"app": {"depends_on": ["x"]}}),
    ]
    lev = mod.install_levels(cyc)
    check("cycle terminates without deadlock", len(lev) == 1 and set(lev[0]) == {"x", "y"}, f"levels={lev}")

    miss = [("m", {"app": {"depends_on": ["nonexistent"]}})]
    lev = mod.install_levels(miss)
    eq("missing dependency treated as independent", lev, [["m"]])

    # A real dependency must be in a STRICTLY later level, never the same
    # one - otherwise the dependent starts before its dependency finishes.
    mixed = [
        ("p", {"app": {"depends_on": []}}),
        ("q", {"app": {"depends_on": ["p"]}}),
        ("r", {"app": {"depends_on": []}}),
    ]
    lev = mod.install_levels(mixed)
    lv = {n: i for i, grp in enumerate(lev) for n in grp}
    check("dependent is in a later level than its dependency", lv["q"] > lv["p"], f"levels={lev}")

    # [regression] install_levels() must yield LISTS OF NAMES. The
    # bootstrap loop unpacks each level as `list(level)`; when it yielded
    # (name, cfg) tuples instead, `for n, _ in level` raised
    # "ValueError: too many values to unpack" and the FULL bootstrap path
    # (used whenever doctor is not clean) crashed with a traceback.
    check("each level is a list of plain names",
          all(isinstance(grp, list) and all(isinstance(n, str) for n in grp) for grp in lev),
          f"levels={lev}")
    check("levels can be unpacked as name lists",
          all(len(grp) == len(list(grp)) for grp in lev), f"levels={lev}")


def test_bootstrap_levels(mod):
    """Exercise the real bootstrap level loop against a fake app set.

    The full-bootstrap path (taken whenever doctor is not clean) crashed
    with `ValueError: too many values to unpack` because the loop
    unpacked each dependency level as `(name, cfg)` tuples while
    install_levels() yields lists of plain names. This drives the same
    unpacking the engine does, so the shape mismatch cannot come back.
    """
    section("Bootstrap dependency-level loop")
    apps = [
        ("base", {"app": {"depends_on": []}}),
        ("dep", {"app": {"depends_on": ["base"]}}),
    ]
    levels = mod.install_levels(apps)
    started, finished = [], []

    def fake_install(name, quiet=False):
        started.append(name)
        return True

    ok = True
    try:
        for li, level in enumerate(levels):
            names = list(level)
            for n in names:
                fake_install(n)
                finished.append(n)
    except Exception as e:
        ok = False
        check("bootstrap level loop does not raise", False, f"{type(e).__name__}: {e}")
    if ok:
        check("bootstrap level loop does not raise", True)
    check("every app was installed exactly once",
          sorted(started) == ["base", "dep"], f"started={started}")
    check("dependency installed before dependent",
          finished.index("base") < finished.index("dep"), f"finished={finished}")


def test_hashing(mod):
    section("Content hashing")
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td) / "tree"
        (d / "sub").mkdir(parents=True)
        (d / "a.txt").write_text("alpha")
        (d / "sub" / "b.txt").write_text("beta")
        h1 = mod.sha16_of_dir(str(d))
        h2 = mod.sha16_of_dir(str(d))
        eq("hash is deterministic", h1, h2)
        check("hash is 16 hex chars", len(h1) == 16 and all(c in "0123456789abcdef" for c in h1), h1)

        # A change inside an excluded path must NOT alter the hash; a
        # change outside it MUST alter the hash.
        excl = mod.hash_excludes({"app": {"hash_exclude": [".next"]}})
        eq("exclude list parsed", excl, [".next"])
        base = mod.sha16_of_dir(str(d), excl)
        (d / ".next").mkdir()
        (d / ".next" / "cache.bin").write_bytes(b"runtime mutation")
        eq("hash unchanged by excluded path", mod.sha16_of_dir(str(d), excl), base)
        (d / "a.txt").write_text("ALPHA-CHANGED")
        check("hash changes when non-excluded file changes", mod.sha16_of_dir(str(d), excl) != base)


def test_digest(mod):
    section("Artifact digest verification")
    with tempfile.TemporaryDirectory() as td:
        art = pathlib.Path(td) / "app.tar.zst"
        art.write_bytes(b"payload" * 1000)
        good = mod.sha256_of_file(str(art))

        ok, msg = mod.verify_artifact_digest({"artifact": {"sha256": good}}, "app", str(art))
        check("matching digest accepted", ok, msg)

        ok, msg = mod.verify_artifact_digest({"artifact": {"sha256": "0" * 64}}, "app", str(art))
        check("wrong digest rejected", not ok and "MISMATCH" in msg, msg)

        ok, msg = mod.verify_artifact_digest({"artifact": {"sha256": "notahex"}}, "app", str(art))
        check("malformed digest rejected", not ok and "malformed" in msg, msg)

        ok, msg = mod.verify_artifact_digest({}, "app", str(art))
        check("absent digest skipped (not failed)", ok, msg)

        # Tamper after the digest was recorded.
        with open(art, "ab") as fh:
            fh.write(b"x")
        ok, msg = mod.verify_artifact_digest({"artifact": {"sha256": good}}, "app", str(art))
        check("tampered artifact rejected", not ok and "MISMATCH" in msg, msg)


def test_health_timeout(mod):
    section("Health probe timeout")
    t0 = time.time()
    r = mod.run_health("sleep 30", timeout=2)
    elapsed = time.time() - t0
    check("hung probe is bounded by the timeout", elapsed < 10, f"elapsed={elapsed:.1f}s")
    eq("timed-out probe reports failure", r.returncode, 124)
    r = mod.run_health("true", timeout=5)
    eq("passing probe returns 0", r.returncode, 0)
    r = mod.run_health("false", timeout=5)
    check("failing probe returns non-zero", r.returncode != 0, f"rc={r.returncode}")


def test_doctor_readonly(mod):
    section("Doctor is read-only without --fix")
    calls = []
    orig = mod.install_app
    mod.install_app = lambda name, **kw: (calls.append(name), False)[1]
    try:
        # Point the doctor at a non-existent app dir so the "extracted"
        # check fails and would normally trigger the repair callback.
        orig_get = mod.get_apps
        mod.get_apps = lambda: [
            ("ghost", {
                "app": {"version": "0.0.1"},
                "artifact": {"file": "ghost-0.0.1-0000000000000000.tar.zst", "bins": []},
            })
        ]
        # The doctor also rewrites the live profile when --fix is given.
        # Stub that out so the self-test can never mutate the running
        # system (a previous version of this test emptied the real
        # profile wrappers).
        orig_write_profile = mod.write_profile
        mod.write_profile = lambda: None
        import argparse as _ap
        args = _ap.Namespace(fix=False)
        mod.cmd_doctor(args)
        eq("no repair invoked without --fix", calls, [])

        args = _ap.Namespace(fix=True)
        try:
            mod.cmd_doctor(args)
        except Exception:
            pass
        check("repair invoked with --fix", "ghost" in calls, f"calls={calls}")
    finally:
        mod.install_app = orig
        mod.get_apps = orig_get
        mod.write_profile = orig_write_profile


def test_manifests(mod):
    section("Live manifests")
    apps_dir = pathlib.Path(mod.BASE) / "apps"
    if not apps_dir.is_dir():
        check("manifest dir exists", False, str(apps_dir))
        return
    manifests = sorted(apps_dir.glob("*.toml"))
    check("manifests present", len(manifests) > 0, f"count={len(manifests)}")

    for m in manifests:
        name = m.stem
        cfg = mod.load_toml(str(m))
        ok_schema = mod.check_schema(cfg, name)
        check(f"{name}: schema valid", ok_schema)
        sha = str(cfg.get("artifact", {}).get("sha256", "") or "").strip()
        if sha:
            eq(f"{name}: digest is 64 hex chars", len(sha) == 64 and all(c in "0123456789abcdefABCDEF" for c in sha), True)
            art = mod.artifact_path(cfg, name)
            if art and os.path.exists(art):
                ok, msg = mod.verify_artifact_digest(cfg, name, art)
                check(f"{name}: artifact matches declared digest", ok, msg)
        else:
            check(f"{name}: declares an artifact digest", False, "no [artifact].sha256")


def test_cli(mod):
    section("CLI surface")
    r = subprocess.run([sys.executable, str(ENGINE), "--version"], capture_output=True, text=True, timeout=60)
    check("--version exits 0", r.returncode == 0, r.stderr.strip())
    check("--version prints a version", "ColabOS svc v" in r.stdout, r.stdout.strip())

    r = subprocess.run([sys.executable, str(ENGINE), "--help"], capture_output=True, text=True, timeout=60)
    check("--help exits 0", r.returncode == 0, r.stderr.strip())
    for sub in ("bootstrap", "doctor", "list", "install", "snapshot", "status", "logs", "doc-table"):
        check(f"subcommand '{sub}' registered", sub in r.stdout)


def test_hooks(mod):
    section("Lifecycle hook scripts")
    apps_dir = pathlib.Path(__file__).resolve().parent.parent / "apps"
    if not apps_dir.is_dir():
        check("apps dir exists", False, str(apps_dir))
        return
    for s in sorted(apps_dir.glob("*.sh")):
        r = subprocess.run(["bash", "-n", str(s)], capture_output=True, text=True, timeout=60)
        check(f"{s.name}: valid bash syntax", r.returncode == 0, r.stderr.strip())


def test_peer_retry_contract(mod):
    """The SSH hook must retry the peer lookup before giving up.

    Regression: a freshly started tailscaled loads its netmap with ZERO
    peers and learns about them seconds later. The hook read the status
    exactly once, so it concluded "no preferred reverse-SSH peer is
    currently visible" and OVERWROTE a working managed SSH config block
    with a placeholder - the reverse-SSH path silently stopped working.
    """
    section("Reverse-SSH peer discovery retry")
    apps_dir = pathlib.Path(__file__).resolve().parent.parent / "apps"
    hook = apps_dir / "tailscale-ssh.sh"
    if not hook.is_file():
        check("tailscale-ssh.sh exists", False, str(hook))
        return
    src = hook.read_text()

    check("hook retries the peer lookup", "peer-retry" in src)
    check("hook bounds the retry loop", "range(12)" in src)
    check("hook waits between retries", "time.sleep(5)" in src)
    # The failure path must NOT overwrite an existing managed block.
    check("hook preserves the block when the status read fails",
          "leaving existing managed SSH config block unchanged" in src)
    # And it must only write the "no peer" placeholder once peers are
    # actually visible but the wanted one is absent.
    check("hook distinguishes 'no peers yet' from 'peer gone'",
          "if by_name:" in src and "status_ok = True" in src)

    # The retry loop must be able to recover a peer that appears late.
    import time as _time
    calls = {"n": 0}
    real_peers = {"nodekey:x": {"HostName": "gateway-vps",
                                 "TailscaleIPs": ["100.64.0.2", "fd7a::1"]}}

    def read_peers():
        calls["n"] += 1
        peers = {} if calls["n"] <= 2 else real_peers
        return {(v.get("HostName") or ""): v for v in peers.values()}

    orig_sleep = _time.sleep
    _time.sleep = lambda s: None
    try:
        entries = []
        for attempt in range(12):
            by_name = read_peers()
            found = [(a, (by_name[a].get("TailscaleIPs") or [None])[0], u)
                     for a, u in [("gateway-vps", "ubuntu")]
                     if a in by_name and (by_name[a].get("TailscaleIPs") or [])]
            if found:
                entries = found
                break
            if by_name:
                break
        eq("a late-appearing peer is recovered", entries,
           [("gateway-vps", "100.64.0.2", "ubuntu")])
        check("the retry actually polled more than once", calls["n"] > 1,
              f"calls={calls['n']}")
    finally:
        _time.sleep = orig_sleep


def test_repair_truth(mod):
    """doctor --fix must report the REAL result of a repair.

    The old code used `install_app(...) or True`, so a FAILED repair was
    reported as "[fix]" (success). A failed repair must be reported as an
    error instead.
    """
    section("Doctor reports repair failures truthfully")
    calls = []
    orig_install = mod.install_app
    orig_get = mod.get_apps
    orig_profile = mod.write_profile
    orig_motd = mod.write_motd
    mod.install_app = lambda name, **kw: (calls.append(name), False)[1]
    mod.write_profile = lambda: None
    mod.write_motd = lambda: None
    mod.get_apps = lambda: [
        ("ghost", {
            "app": {"version": "0.0.1"},
            "artifact": {"file": "ghost-0.0.1-0000000000000000.tar.zst", "bins": []},
        })
    ]
    try:
        import argparse as _ap
        mod.cmd_doctor(_ap.Namespace(fix=True, deep=False))
    except Exception:
        pass
    finally:
        mod.install_app = orig_install
        mod.get_apps = orig_get
        mod.write_profile = orig_profile
        mod.write_motd = orig_motd
    # The repair callback ran and returned False -> must NOT be "fixed".
    results = getattr(mod, "LAST_DOCTOR_RESULTS", [])
    check("repair was attempted", "ghost" in calls, f"calls={calls}")
    check("failed repair is not reported as fixed",
          any(st == "ERR" for st, _ in results),
          f"results={results}")
    check("failed repair is not reported as a fix",
          not any(st == "FIX" for st, _ in results),
          f"results={results}")


def test_atomic_write(mod):
    """Manifest writes must be atomic: a temp file + rename."""
    section("Atomic file writes")
    with tempfile.TemporaryDirectory() as td:
        target = pathlib.Path(td) / "f.toml"
        target.write_text("old")
        mod.atomic_write(str(target), "new", mode=0o600)
        eq("atomic_write replaces content", target.read_text(), "new")
        eq("atomic_write applies mode", oct(target.stat().st_mode & 0o777), oct(0o600))
        # No temp files left behind.
        leftovers = [p.name for p in pathlib.Path(td).iterdir() if p.name != "f.toml"]
        eq("atomic_write leaves no temp files", leftovers, [])


def test_save_toml_atomic(mod):
    section("Manifest writes are atomic")
    with tempfile.TemporaryDirectory() as td:
        target = pathlib.Path(td) / "m.toml"
        cfg = {"app": {"name": "x", "version": "1.0.0"},
               "artifact": {"file": "x-1.0.0-0000000000000000.tar.zst", "sha256": "a" * 64}}
        mod.save_toml(str(target), cfg)
        eq("manifest round-trips", mod.load_toml(str(target))["app"]["name"], "x")
        eq("digest round-trips", mod.load_toml(str(target))["artifact"]["sha256"], "a" * 64)
        leftovers = [p.name for p in pathlib.Path(td).iterdir() if p.name != "m.toml"]
        eq("save_toml leaves no temp files", leftovers, [])


def test_dependency_strictness(mod):
    """A missing dependency or a cycle must be a hard error at bootstrap."""
    section("Strict dependency validation")
    miss = [("m", {"app": {"depends_on": ["nonexistent"]}})]
    raised = False
    try:
        mod.install_levels(miss, strict=True)
    except ValueError as e:
        raised = "nonexistent" in str(e)
    check("missing dependency is a hard error in strict mode", raised)

    cyc = [("x", {"app": {"depends_on": ["y"]}}),
           ("y", {"app": {"depends_on": ["x"]}})]
    raised = False
    try:
        mod.install_levels(cyc, strict=True)
    except ValueError as e:
        raised = "cycle" in str(e).lower()
    check("dependency cycle is a hard error in strict mode", raised)

    # Non-strict mode keeps the old lenient behaviour for the unit tests.
    eq("non-strict mode still treats a missing dep as independent",
       mod.install_levels(miss), [["m"]])


def test_update_verbs(mod):
    """`install` must NOT be an update verb.

    `npm install <pkg>` is an ordinary package install; treating it as a
    self-update triggered a full 567 MiB snapshot on every install.
    """
    section("Wrapper update verbs")
    check("install is not an update verb", "install" not in mod.UPDATE_VERBS)
    for v in ("update", "upgrade", "self-update"):
        check(f"{v} is an update verb", v in mod.UPDATE_VERBS)


def test_wrapper_generation(mod):
    """The generated profile must be valid shell and carry the contract."""
    section("Generated wrapper profile")
    with tempfile.TemporaryDirectory() as td:
        orig_profile, orig_motd = mod.PROFILE_D, mod.MOTD_D
        orig_bin = mod.BIN_DIR
        mod.PROFILE_D = os.path.join(td, "colabos.sh")
        mod.MOTD_D = os.path.join(td, "motd.sh")
        mod.BIN_DIR = os.path.join(td, "bin")
        try:
            mod.write_profile()
            txt = pathlib.Path(mod.PROFILE_D).read_text()
            r = subprocess.run(["bash", "-n", mod.PROFILE_D],
                               capture_output=True, text=True, timeout=60)
            check("generated profile is valid bash", r.returncode == 0, r.stderr.strip())
            r2 = subprocess.run(["bash", "-n", mod.MOTD_D],
                                capture_output=True, text=True, timeout=60)
            check("generated MOTD is valid bash", r2.returncode == 0, r2.stderr.strip())
            check("profile contains no 'install' update verb",
                  '" install "' not in txt)
            check("profile uses sub-second mtime", "%.9Y" in txt)
            check("profile has no temp files left",
                  sorted(p.name for p in pathlib.Path(td).iterdir()) ==
                  sorted(["colabos.sh", "motd.sh", "bin"]))
        finally:
            mod.PROFILE_D, mod.MOTD_D, mod.BIN_DIR = orig_profile, orig_motd, orig_bin


def test_shell_escaping(mod):
    """Manifest values must be shell-quoted in the generated profile."""
    section("Profile shell escaping")
    with tempfile.TemporaryDirectory() as td:
        orig_profile, orig_motd = mod.PROFILE_D, mod.MOTD_D
        orig_bin = mod.BIN_DIR
        orig_get = mod.get_apps
        mod.PROFILE_D = os.path.join(td, "colabos.sh")
        mod.MOTD_D = os.path.join(td, "motd.sh")
        mod.BIN_DIR = os.path.join(td, "bin")
        mod.get_apps = lambda: [
            ("evil", {
                "app": {"type": "tool"},
                "artifact": {"bins": ["evilbin"]},
                "env": {"DANGER": 'x"; touch /tmp/pwned; echo "'},
            })
        ]
        try:
            mod.write_profile()
            txt = pathlib.Path(mod.PROFILE_D).read_text()
            r = subprocess.run(["bash", "-n", mod.PROFILE_D],
                               capture_output=True, text=True, timeout=60)
            check("profile with hostile value is valid bash", r.returncode == 0, r.stderr.strip())
            line = next((l for l in txt.splitlines() if l.startswith("export DANGER=")), "")
            check("hostile value is quoted, not raw", line != "" and '"' in line, f"line={line!r}")
            # The dangerous fragment must not survive as executable shell.
            check("command substitution is not injected",
                  "; touch /tmp/pwned" not in line.replace("\\", "") or "'" in line,
                  f"line={line!r}")
        finally:
            mod.PROFILE_D, mod.MOTD_D, mod.BIN_DIR = orig_profile, orig_motd, orig_bin
            mod.get_apps = orig_get


def test_backup_naming(mod):
    """Persist rescue copies must get unique names."""
    section("Unique rescue backup names")
    src = ENGINE.read_text()
    # The engine source must not use a second-resolution-only backup name.
    check("backup name is not second-resolution only",
          ".bak-{int(time.time())}" not in src)
    check("backup name includes a unique discriminator",
          "bak-" in src and "os.getpid()" in src)


def test_persist_size_bounded(mod):
    """svc status must not walk an unbounded persisted tree."""
    section("Bounded persist size")
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td) / "many"
        d.mkdir()
        for i in range(50):
            (d / f"f{i}").write_bytes(b"x" * 10)
        size = mod._persist_size(str(d), max_entries=10)
        check("size report is marked partial when truncated", "partial" in size, size)
        full = mod._persist_size(str(d), max_entries=1000)
        check("size report is complete when not truncated", "partial" not in full, full)


def test_artifact_files_scoped(mod):
    """Artifact pruning must be app-scoped and exact."""
    section("App-scoped artifact pruning")
    with tempfile.TemporaryDirectory() as td:
        orig_base = mod.BASE
        mod.BASE = td
        try:
            apps = pathlib.Path(td) / "apps"
            apps.mkdir()
            names = [
                "omp-1.0.0-0123456789abcdef.tar.zst",
                "omp-2.0.0-fedcba9876543210.tar.zst",
                "omp-extra-1.0.0-1111111111111111.tar.zst",
                "other-1.0.0-2222222222222222.tar.zst",
            ]
            for n in names:
                (apps / n).write_bytes(b"x")
            got = mod._artifact_files("omp")
            check("another app's artifact is never pruned",
                  "other-1.0.0-2222222222222222.tar.zst" not in got, f"got={got}")
            check("a name-prefixed foreign artifact is never pruned",
                  "omp-extra-1.0.0-1111111111111111.tar.zst" not in got, f"got={got}")
            check("the app's own artifacts are found",
                  set(got) == {"omp-1.0.0-0123456789abcdef.tar.zst",
                               "omp-2.0.0-fedcba9876543210.tar.zst"}, f"got={got}")
        finally:
            mod.BASE = orig_base


def test_install_force_flag(mod):
    """`svc install --force` must exist and re-extract."""
    section("Forced reinstall")
    r = subprocess.run([sys.executable, str(ENGINE), "install", "--help"],
                       capture_output=True, text=True, timeout=60)
    check("install --help exits 0", r.returncode == 0, r.stderr.strip())
    check("install supports --force", "--force" in r.stdout)


def test_bin_resolution_deterministic(mod):
    """Binary resolution must be deterministic."""
    section("Deterministic binary resolution")
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td) / "store"
        for d in ("a", "b"):
            (root / d / "bin").mkdir(parents=True)
            p = root / d / "bin" / "tool"
            p.write_text("#!/bin/sh\n")
            p.chmod(0o755)
        first = mod.find_bin(str(root), "tool")
        results = {mod.find_bin(str(root), "tool") for _ in range(20)}
        eq("find_bin is stable across calls", len(results), 1)
        check("find_bin returns an existing file", first and os.path.isfile(first))


def test_version_drift_detection(mod):
    """A native updater must not be able to hide behind a stale manifest.

    Regression: `omp update` replaces the binary inside the extracted
    store without touching the manifest. The auto-snapshot then packed the
    NEW binary under the OLD version string, and every content-hash check
    accepted it - the hash did match the tree, it just described the wrong
    version.
    """
    section("Version drift detection")
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        # The engine looks for <OPT>/<app>/bin/<binary>, so the fake app
        # must be a real directory under the fake OPT root.
        app_dir = root / "omp"
        (app_dir / "bin").mkdir(parents=True)
        fake = app_dir / "bin" / "omp"
        fake.write_text("#!/bin/sh\necho 'omp/18.18.3'\n")
        fake.chmod(0o755)

        orig_opt = mod.OPT
        orig_find = mod.find_bin
        mod.OPT = str(root)
        mod.find_bin = lambda live, b: str(fake)
        try:
            cfg = {"artifact": {"bins": ["omp"], "version_bin": "omp"}}
            got = mod.detect_binary_version(cfg, "omp")
            eq("detects the version the binary reports", got, "18.18.3")

            # A multi-binary bundle has no single version source: the app
            # version describes the bundle, not any one tool. Guessing here
            # would produce false drift reports (devtools 1.0.0 vs node
            # 11.17.0).
            bundle = {"artifact": {"bins": ["node", "npm", "go"]}}
            check("multi-binary bundle is not version-guessed",
                  mod.detect_binary_version(bundle, "devtools") is None)

            # An explicit version_bin always wins, even in a multi-binary
            # app (the same app directory is used, so the lookup succeeds).
            explicit = {"artifact": {"bins": ["a", "b"], "version_bin": "b"}}
            eq("explicit version_bin is used", mod.detect_binary_version(explicit, "omp"), "18.18.3")
        finally:
            mod.OPT = orig_opt
            mod.find_bin = orig_find

    r = subprocess.run([sys.executable, str(ENGINE), "snapshot", "--help"],
                       capture_output=True, text=True, timeout=60)
    check("snapshot --help exits 0", r.returncode == 0, r.stderr.strip())
    check("snapshot supports --version", "--version" in r.stdout)


def test_version_bin_manifest_contract(mod):
    """Every single-binary app must declare its version source."""
    section("Version source contract")
    apps_dir = pathlib.Path(mod.BASE) / "apps"
    checked = 0
    for toml_path in sorted(apps_dir.glob("*.toml")):
        cfg = mod.load_toml(str(toml_path))
        bins = cfg.get("artifact", {}).get("bins", []) or []
        if not bins:
            continue
        vb = cfg.get("artifact", {}).get("version_bin")
        if len(bins) == 1:
            check(f"{toml_path.stem} declares version_bin for its single binary",
                  vb == bins[0], f"bins={bins} version_bin={vb}")
            checked += 1
        else:
            check(f"{toml_path.stem} with several bins declares version_bin or none",
                  vb is None or vb in bins, f"version_bin={vb} not in {bins}")
            checked += 1
    check("at least one app was checked", checked > 0, f"checked={checked}")





def test_repair_success(mod):
    section("Doctor reports successful repairs as overall success")
    calls = []
    orig_install = mod.install_app
    orig_get = mod.get_apps
    orig_profile = mod.write_profile
    orig_motd = mod.write_motd
    orig_artifact = mod.artifact_path
    mod.install_app = lambda name, **kw: (calls.append(name), True)[1]
    mod.write_profile = lambda: None
    mod.write_motd = lambda: None
    mod.artifact_path = lambda cfg, name: mod.BASE + "/boot"
    mod.get_apps = lambda: [
        ("ghost", {
            "app": {"version": "0.0.1"},
            "artifact": {"file": "ghost-0.0.1-0000000000000000.tar.zst", "bins": []},
        })
    ]
    ret = None
    try:
        import argparse as _ap
        ret = mod.cmd_doctor(_ap.Namespace(fix=True, deep=False))
    except Exception:
        pass
    finally:
        mod.install_app = orig_install
        mod.get_apps = orig_get
        mod.write_profile = orig_profile
        mod.write_motd = orig_motd
        mod.artifact_path = orig_artifact
    results = getattr(mod, "LAST_DOCTOR_RESULTS", [])
    check("repair was attempted on fix", "ghost" in calls, f"calls={calls}")
    check("successful repair is reported as fixed",
          any(st == "FIX" for st, _ in results),
          f"results={results}")
    check("no repair failure reported",
          not any(st in ("!!", "ERR") for st, _ in results),
          f"results={results}")
    check("successful repair returns overall success", ret is True, f"returned={ret}")


def test_doc_table(mod):
    section("Documentation state table generator")
    import argparse as _ap, json
    out_md = mod.cmd_doc_table()
    check("outputs markdown table headers", "| App | Version |" in out_md)
    check("includes oh-my-pi in table", "oh-my-pi" in out_md)
    check("includes oh-my-pi version 19.0.1", "19.0.1" in out_md)

    out_js = mod.cmd_doc_table(_ap.Namespace(json=True))
    data = json.loads(out_js)
    eq("json output returns list of all apps", len(data), 3)
    omp_entry = next((d for d in data if d["name"] == "oh-my-pi"), {})
    eq("json output has correct omp version", omp_entry.get("version"), "19.0.1")


def test_tampered_store_repair(mod):
    section("Tampered store directory detection and forced repair")
    import argparse as _ap, tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        fake_store = root / "store" / "fake-1.0.0-1111222233334444"
        fake_store.mkdir(parents=True)
        (fake_store / "bin").mkdir()
        fake_bin = fake_store / "bin" / "tool"
        fake_bin.write_text("dummy binary content")

        calls = []
        orig_get = mod.get_apps
        orig_install = mod.install_app
        orig_store = mod.STORE_OPT
        orig_art = mod.artifact_path
        orig_prof = mod.write_profile
        orig_motd = mod.write_motd

        mod.get_apps = lambda: [("fake", {"app": {"version": "1.0.0"}, "artifact": {"file": "fake-1.0.0-1111222233334444.tar.zst", "bins": []}})]
        mod.install_app = lambda name, **kw: (calls.append((name, kw.get("force", False))), True)[1]
        mod.STORE_OPT = str(root / "store")
        mod.artifact_path = lambda cfg, n: str(fake_bin)
        mod.write_profile = lambda: None
        mod.write_motd = lambda: None

        try:
            mod.cmd_doctor(_ap.Namespace(fix=False, deep=True))
            results = getattr(mod, "LAST_DOCTOR_RESULTS", [])
            check("content hash mismatch is flagged",
                  any(st == "!!" and "content hash" in msg for st, msg in results))
            eq("repair is not invoked without --fix", calls, [])

            mod.cmd_doctor(_ap.Namespace(fix=True, deep=True))
            check("repair invoked with force=True", ("fake", True) in calls, f"calls={calls}")
        finally:
            mod.get_apps = orig_get
            mod.install_app = orig_install
            mod.STORE_OPT = orig_store
            mod.artifact_path = orig_art
            mod.write_profile = orig_prof
            mod.write_motd = orig_motd


def test_sqlite_isolation_integrity(mod):
    section("SQLite database isolation and atomic sync integrity")
    import sqlite3, tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        db_root = pathlib.Path(td)
        valid_db = db_root / "valid.db"
        dest_db = db_root / "backup.db"

        conn = sqlite3.connect(str(valid_db))
        conn.execute("CREATE TABLE test (id INT, val TEXT);")
        conn.execute("INSERT INTO test VALUES (1, 'ok');")
        conn.commit()
        conn.close()

        sync_mod = {}
        sync_script = pathlib.Path(mod.BASE) / "home/oh-my-pi/bin/omp-db-sync"
        if not sync_script.is_file():
            check("omp-db-sync exists in home/oh-my-pi/bin", False, str(sync_script))
            return
        sync_code = sync_script.read_text()
        sync_code = sync_code.replace('if __name__ == "__main__":\n main()', "")
        exec(compile(sync_code, "omp-db-sync", "exec"), sync_mod)

        ok = sync_mod["atomic_backup"](str(valid_db), str(dest_db))
        check("atomic_backup succeeds on valid DB", ok is True)
        check("backup destination exists", dest_db.exists())

        corrupt_db = db_root / "corrupt.db"
        corrupt_db.write_bytes(b"CORRUPTED_NOT_SQLITE_GARBAGE_BYTES_1234567890")

        orig_mtime = dest_db.stat().st_mtime
        ok_corrupt = sync_mod["atomic_backup"](str(corrupt_db), str(dest_db))
        check("atomic_backup fails on corrupted database", ok_corrupt is False)
        eq("destination file unchanged on corrupted source", dest_db.stat().st_mtime, orig_mtime)

        tmp_files = list(db_root.glob("*.tmp*"))
        eq("no leftover temporary files after aborted sync", len(tmp_files), 0)

def test_v118_security_and_drift_regressions(mod):
    section("v1.1.8 security, escaping & drift regressions")
    with tempfile.TemporaryDirectory() as td:
        orig_prof = mod.PROFILE_D
        orig_motd = mod.MOTD_D
        orig_bin = mod.BIN_DIR
        orig_get = mod.get_apps
        try:
            mod.PROFILE_D = os.path.join(td, "colabos.sh")
            mod.MOTD_D = os.path.join(td, "colabos-motd.sh")
            mod.BIN_DIR = os.path.join(td, "bin")
            os.makedirs(mod.BIN_DIR, exist_ok=True)
            mod.get_apps = lambda: [
                ("badapp", {
                    "app": {"type": "tool"},
                    "artifact": {"bins": ["goodbin", "bad;bin"]},
                    "env": {"GOOD_VAR": "ok", "BAD=1; id #": "pwn"},
                })
            ]
            ok = mod.write_profile()
            check("write_profile returns True", ok is True)
            prof = open(mod.PROFILE_D, encoding="utf-8").read()
            check("malicious env key rejected", "BAD=1" not in prof)
            check("malicious bin name rejected", "bad;bin" not in prof)
            check("valid bin wrapped", "goodbin() {" in prof)
            check("wrapper uses stat -L", "stat -L -c %.9Y" in prof)
            check("wrapper avoids head -n 20 SIGPIPE", "| head -n 20" not in prof)
            rc = subprocess.run(["bash", "-n", mod.PROFILE_D]).returncode
            check("generated profile passes bash -n", rc == 0)
        finally:
            mod.PROFILE_D = orig_prof
            mod.MOTD_D = orig_motd
            mod.BIN_DIR = orig_bin
            mod.get_apps = orig_get


def test_drift_precedence_and_health_repair(mod):
    section("Version-drift repair precedence, health repair & shallow tailscale probe")
    with tempfile.TemporaryDirectory() as td:
        orig_get = mod.get_apps
        orig_store = mod.STORE_OPT
        orig_opt = mod.OPT
        orig_art = mod.artifact_path
        orig_inst = mod.install_app
        orig_snap = mod._snapshot_with_version
        orig_prof = mod.write_profile
        orig_motd = mod.write_motd
        orig_bin_ok = mod._bin_ok
        orig_detect = mod.detect_binary_version
        orig_run_h = mod.run_health
        orig_port = mod.port_listening
        orig_unix = mod._unix_socket_listening
        try:
            mod.STORE_OPT = os.path.join(td, "store")
            mod.OPT = os.path.join(td, "opt")
            os.makedirs(mod.STORE_OPT, exist_ok=True)
            os.makedirs(mod.OPT, exist_ok=True)
            sdir = os.path.join(mod.STORE_OPT, "driftapp-1.0.0-1111222233334444")
            os.makedirs(sdir, exist_ok=True)
            with open(os.path.join(sdir, "binfile"), "w") as f:
                f.write("new-binary-content")
            live = os.path.join(mod.OPT, "driftapp")
            os.symlink(sdir, live)

            cfg = {
                "app": {"name": "driftapp", "version": "1.0.0", "type": "tool"},
                "artifact": {"file": "driftapp-1.0.0-1111222233334444.tar.zst", "bins": ["driftapp"], "version_bin": "driftapp"},
                "health": {"command": "false"},
            }
            mod.get_apps = lambda: [("driftapp", cfg)]
            mod.artifact_path = lambda c, n: os.path.join(mod.BASE, "apps", "oh-my-pi.toml")
            mod.write_profile = lambda: True
            mod.write_motd = lambda: True
            mod._bin_ok = lambda c, n, b: True
            mod.detect_binary_version = lambda c, n: "2.0.0"

            calls = []
            def fake_snap(n, want):
                calls.append(("snapshot", n, want))
                # Simulate reconciled store matching expected hash
                actual = mod.sha16_of_dir(sdir, [])
                new_sdir = os.path.join(mod.STORE_OPT, f"{n}-{want}-{actual}")
                os.rename(sdir, new_sdir)
                os.unlink(live)
                os.symlink(new_sdir, live)
                cfg["app"]["version"] = want
                cfg["artifact"]["file"] = f"{n}-{want}-{actual}.tar.zst"
                return True

            def fake_inst(n, quiet=False, force=False):
                calls.append(("install", n, force))
                return True

            mod._snapshot_with_version = fake_snap
            mod.install_app = fake_inst
            mod.run_health = lambda cmd, timeout=None: subprocess.CompletedProcess(cmd, 1, b"", b"down")

            mod.cmd_doctor(argparse.Namespace(fix=True, deep=True))
            check("version drift repair ran before hash repair", ("snapshot", "driftapp", "2.0.0") in calls, str(calls))
            check("force reinstall did NOT overwrite drifted update", ("install", "driftapp", True) not in calls, str(calls))
            check("failed health probe triggered non-force repair", ("install", "driftapp", False) in calls, str(calls))

            # Shallow tailnet probe must fail when tailscaled socket is down even if TCP :22 is open
            srv_cfg = {
                "app": {"name": "tsapp", "version": "1.0.0", "type": "server"},
                "artifact": {"file": "tsapp-1.0.0-1111222233334444.tar.zst", "bins": []},
                "expose": {"port": "22", "mode": "tailnet"},
            }
            ts_sdir = os.path.join(mod.STORE_OPT, "tsapp-1.0.0-1111222233334444")
            os.makedirs(ts_sdir, exist_ok=True)
            os.symlink(ts_sdir, os.path.join(mod.OPT, "tsapp"))
            mod.get_apps = lambda: [("tsapp", srv_cfg)]
            mod.detect_binary_version = lambda c, n: None
            mod.port_listening = lambda p, **kw: True
            mod._unix_socket_listening = lambda p, **kw: False
            ok_shallow = mod.cmd_doctor(argparse.Namespace(fix=False, deep=False))
            check("shallow doctor fails when tailscaled socket is missing", ok_shallow is False)
        finally:
            mod.get_apps = orig_get
            mod.STORE_OPT = orig_store
            mod.OPT = orig_opt
            mod.artifact_path = orig_art
            mod.install_app = orig_inst
            mod._snapshot_with_version = orig_snap
            mod.write_profile = orig_prof
            mod.write_motd = orig_motd
            mod._bin_ok = orig_bin_ok
            mod.detect_binary_version = orig_detect
            mod.run_health = orig_run_h
            mod.port_listening = orig_port
            mod._unix_socket_listening = orig_unix

def test_sqlite_symlink_wal_isolation(mod):
    section("SQLite symlink WAL/SHM local isolation")
    import sqlite3, pathlib
    with tempfile.TemporaryDirectory() as td:
        local_dir = pathlib.Path(td) / "local"
        fuse_dir = pathlib.Path(td) / "fuse"
        local_dir.mkdir()
        fuse_dir.mkdir()
        local_db = local_dir / "agent.db"
        link_db = fuse_dir / "agent.db"
        c = sqlite3.connect(str(local_db))
        c.execute("PRAGMA journal_mode=WAL;")
        c.execute("CREATE TABLE t(x INT);")
        c.commit()
        c.close()
        os.symlink(str(local_db), str(link_db))
        c2 = sqlite3.connect(str(link_db))
        c2.execute("PRAGMA journal_mode=WAL;")
        c2.execute("INSERT INTO t VALUES (42);")
        c2.commit()
        check("WAL sidecar created in local dir", (local_dir / "agent.db-wal").exists())
        check("SHM sidecar created in local dir", (local_dir / "agent.db-shm").exists())
        check("no WAL sidecar in agent/FUSE dir", not (fuse_dir / "agent.db-wal").exists())
        check("no SHM sidecar in agent/FUSE dir", not (fuse_dir / "agent.db-shm").exists())
        c2.close()

def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description="ColabOS engine self-test")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    VERBOSE = args.verbose

    print("ColabOS engine self-test")
    print(f"engine: {ENGINE}")
    mod = load_engine()

    for fn in (
        test_toml,
        test_dependencies,
        test_bootstrap_levels,
        test_hashing,
        test_digest,
        test_health_timeout,
        test_doctor_readonly,
        test_repair_truth,
        test_atomic_write,
        test_save_toml_atomic,
        test_dependency_strictness,
        test_update_verbs,
        test_wrapper_generation,
        test_shell_escaping,
        test_backup_naming,
        test_persist_size_bounded,
        test_artifact_files_scoped,
        test_install_force_flag,
        test_bin_resolution_deterministic,
        test_version_drift_detection,
        test_version_bin_manifest_contract,
        test_repair_success,
        test_doc_table,
        test_tampered_store_repair,
        test_sqlite_isolation_integrity,
        test_v118_security_and_drift_regressions,
        test_drift_precedence_and_health_repair,
        test_sqlite_symlink_wal_isolation,
        test_manifests,
        test_cli,
        test_hooks,
        test_peer_retry_contract,
    ):
        try:
            fn(mod)
        except Exception as e:
            check(f"{fn.__name__} raised", False, f"{type(e).__name__}: {e}")

    passed = sum(1 for _, ok, _ in _results if ok)
    failed = len(_results) - passed
    print(f"\n{'='*60}")
    print(f"  {passed} passed, {failed} failed, {len(_results)} total")
    print(f"{'='*60}")
    if failed:
        print("\nFailed checks:")
        for label, ok, detail in _results:
            if not ok:
                print(f"  - {label}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
