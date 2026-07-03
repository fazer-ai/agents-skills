#!/usr/bin/env python3
# Generic remote-bash runner for the fazer.ai agents onboarding. ONE job: run an arbitrary bash script on a
# host over SSH WITHOUT the agent hand-assembling it on the PowerShell command line. That assembly is the
# footgun that reappears every new context on Windows, in two distinct shapes (both seen in real runs):
#
#   1. Eaten quotes. `ssh <host> 'docker network ls --format "{{.Name}}" | grep -vE "^(a|b)$"'`, the inner
#      double quotes are swallowed by Windows native-arg parsing on the way to ssh.exe, so the remote bash
#      gets `{{.Name}}` / `^(a|b)$` UNQUOTED and dies with `syntax error near unexpected token '('`.
#   2. BOM on a here-string. `@'...set -euo pipefail...'@ | ssh ... 'bash -s'`, PowerShell prepends a UTF-8
#      BOM to the piped text; the remote bash reads `﻿set` as an unknown command on line 1, so the
#      guard never arms and the rest of a (possibly destructive) script runs unguarded.
#
# Both vanish with the same move: write the script to a `.sh` file (with the editing tool, no shell in the
# loop) and feed it to the remote `bash -s` through THIS helper, which streams the bytes to ssh's stdin via
# a DIRECT argv list (no local shell). The script content never touches a command line, so quotes, `$()`,
# `{{...}}`, `(`, heredocs and newlines arrive byte-for-byte on every OS. Same payload-owning pattern as
# coolify.py (psql) and docker-status.py (`docker ps`), generalized to any script.
#
#   remote.py --ssh root@HOST --ssh-opts "-i ~/.ssh/key" --script-file recon.sh             # stream output
#   remote.py --ssh root@HOST --ssh-opts "-i ~/.ssh/key" --script-file wipe.sh --sudo        # via sudo -n
#   remote.py --ssh ... --in-container coolify-db --exec "psql -U coolify -d coolify" --script-file q.sql  # psql in a container
#   remote.py --ssh ... --in-container <rails-c> --exec "bundle exec rails runner -" --script-file t.rb     # rails runner
#   remote.py --ssh root@HOST --ssh-opts "-i ~/.ssh/key" --script-file x.sh --capture        # JSON result
#   remote.py --ssh root@HOST --ssh-opts "-i ~/.ssh/key" --script-file x.sh --dry-run         # argv+preview
#
# Same payload-on-stdin trick for a console INSIDE a container: psql and `rails runner -` read their program
# from stdin, so --in-container/--exec delivers a .sql/.rb file byte-exact too (the `\` of a PHP/Ruby
# namespace, accents, quotes, none of it touches a command line).
#
# Python 3 stdlib only (no pip). Runs ssh via Bash with dangerouslyDisableSandbox:true (it is network),
# same as sshkey.py/docker-status.py. Output streams live by default (long installs do not look hung and
# do not trip the harness timeout); exit code is propagated. --capture buffers and returns JSON instead.
import argparse
import json
import os
import re
import shlex
import subprocess
import sys

BOM = b"\xef\xbb\xbf"
# Container name is interpolated into the remote command, so keep it to a safe bare token.
SAFE_TOKEN = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
# --exec is the in-container program that reads the script from stdin (psql / rails runner -). Allow only
# bare words, flags and the punctuation those need, no shell metacharacters that the remote shell would act on.
EXEC_OK = re.compile(r"^[A-Za-z0-9 _=:./-]+$")
# Git Bash/MSYS on Windows reports paths as "/c/Users/..." (or "/mnt/c/..." under WSL), but native Python
# on Windows cannot open those: it needs "C:\Users\...". Match a leading drive segment so we can retranslate.
MSYS_DRIVE_RE = re.compile(r"^/(?:mnt/)?([A-Za-z])/(.*)$")


def out(obj, code=0):
    print(json.dumps(obj))
    sys.exit(code)


def fail(msg, **extra):
    out({"ok": False, "error": msg, **extra}, code=1)


def msys_to_native(path):
    # Translate a Git Bash/MSYS/WSL path ("/c/Users/me/x.sh", "/mnt/c/Users/me/x.sh") to the native Windows
    # form ("C:\Users\me\x.sh") so open() finds it. Returns None when the path is not drive-prefixed (nothing
    # to translate). POSIX paths and already-native Windows paths ("C:\...", "C:/...") are left to open() as-is.
    m = MSYS_DRIVE_RE.match(path)
    if not m:
        return None
    drive, rest = m.group(1), m.group(2)
    return f"{drive.upper()}:\\" + rest.replace("/", "\\")


def split_ssh_opts(opts, _nt=None):
    # POSIX shlex eats backslashes, so a Windows key path ("-i C:\Users\me\.ssh\key") would arrive as
    # "C:Usersme.sshkey". On Windows, tokenize WITHOUT escape processing and strip the surrounding quotes
    # ourselves so backslashes survive. _nt is injectable for tests. (Kept in sync with docker-status.py.)
    nt = (os.name == "nt") if _nt is None else _nt
    if not opts:
        return []
    if nt:
        toks = shlex.split(opts, posix=False)
        return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t for t in toks]
    return shlex.split(opts)


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def read_script(path):
    if path == "-":
        data = sys.stdin.buffer.read()
    else:
        try:
            data = _read_bytes(path)
        except OSError as exc:
            # A Git Bash/MSYS path ("/c/Users/me/x.sh") reaches native Windows Python verbatim and fails to
            # open; retry the translated native form ("C:\Users\me\x.sh") before giving up.
            native = msys_to_native(path)
            if native is None:
                fail(f"cannot read --script-file {path!r}: {exc}")
            try:
                data = _read_bytes(native)
            except OSError as exc2:
                fail(f"cannot read --script-file {path!r} (tried {native!r}): {exc2}")
    # Strip a stray UTF-8 BOM defensively: a PowerShell here-string / `Out-File` adds one and it breaks the
    # script's first line (the exact failure this helper exists to remove). We deliver the rest byte-exact.
    if data[:3] == BOM:
        data = data[3:]
    if not data.strip():
        fail("script is empty")
    return data


def build_argv(args, remote):
    return [
        "ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={args.connect_timeout}",
        "-o", "StrictHostKeyChecking=accept-new", *split_ssh_opts(args.ssh_opts), args.ssh, remote,
    ]


def remote_command(args):
    # The remote command carries NO payload; it just starts the interpreter; the script rides in on stdin,
    # so it never hits a command line. `bash -s` and `docker exec -i <c> <prog>` (psql, `rails runner -`)
    # all read their program from stdin. `sudo -n` fails fast instead of hanging on a password prompt.
    if args.in_container:
        if any(c not in SAFE_TOKEN for c in args.in_container):
            fail(f"invalid --in-container {args.in_container!r} (expected a bare [A-Za-z0-9._-] token)")
        inner = args.exec or "bash -s"
        if not EXEC_OK.match(inner):
            fail(f"invalid --exec {inner!r} (bare words/flags only: [A-Za-z0-9 _=:./-])")
        base = f"docker exec -i {args.in_container} {inner}"
    else:
        base = "bash -s"
    return f"sudo -n -- {base}" if args.sudo else base


def cmd_run(args):
    script = read_script(args.script_file)
    remote = remote_command(args)
    argv = build_argv(args, remote)
    if args.dry_run:
        preview = script[:400].decode("utf-8", "replace")
        out({
            "ok": True, "dry_run": True, "remote_cmd": remote, "argv": argv,
            "script_bytes": len(script), "script_preview": preview,
        })
    timeout = args.timeout or None
    try:
        if args.capture:
            proc = subprocess.run(argv, input=script, capture_output=True, timeout=timeout)
            ok = proc.returncode == 0
            out({
                "ok": ok, "exit_code": proc.returncode,
                "stdout": proc.stdout.decode("utf-8", "replace"),
                "stderr": proc.stderr.decode("utf-8", "replace"),
            }, code=0 if ok else 1)
        # Stream mode: inherit stdout/stderr so the agent sees output live; feed the script on stdin.
        proc = subprocess.run(argv, input=script, timeout=timeout)
        sys.exit(proc.returncode)
    except FileNotFoundError:
        fail("ssh not found on PATH")
    except subprocess.TimeoutExpired:
        fail("ssh timed out", remote_cmd=remote)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="remote.py",
        description="Run an arbitrary bash script on a host over SSH (payload-owning; survives "
        "PowerShell->SSH). Write the script to a .sh file and point --script-file at it.",
    )
    parser.add_argument("--ssh", required=True, metavar="USER@HOST")
    parser.add_argument("--ssh-opts", default="", help="extra ssh options, e.g. '-i ~/.ssh/key -p 2222'")
    parser.add_argument("--script-file", required=True, metavar="PATH",
                        help="path to the bash script to run remotely ('-' reads stdin; avoid '-' on PowerShell)")
    parser.add_argument("--in-container", default="", metavar="NAME",
                        help="pipe the script into `docker exec -i NAME ...` on the host (console in a container)")
    parser.add_argument("--exec", default="", metavar="CMD",
                        help="program inside --in-container that reads the script on stdin, e.g. "
                        "'psql -U coolify -d coolify -v ON_ERROR_STOP=1' or 'bundle exec rails runner -' (default: bash -s)")
    parser.add_argument("--sudo", action="store_true", help="run via `sudo -n -- …` (works with bash -s and --in-container)")
    parser.add_argument("--capture", action="store_true",
                        help="buffer and print {ok, exit_code, stdout, stderr} as JSON instead of streaming")
    parser.add_argument("--connect-timeout", type=int, default=12)
    parser.add_argument("--timeout", type=int, default=0, help="ssh timeout in seconds (0 = no limit; installs run long)")
    parser.add_argument("--dry-run", action="store_true", help="print the argv + script preview, do not connect")
    parser.set_defaults(fn=cmd_run)
    return parser


def main():
    args = build_parser().parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
