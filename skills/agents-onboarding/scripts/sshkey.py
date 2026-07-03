#!/usr/bin/env python3
# SSH key helper for the fazer.ai agents onboarding. Two jobs:
#   generate   create a dedicated ed25519 key and print the PUBLIC half for the operator to paste in the
#              VPS panel. ssh-keygen is spawned with a DIRECT argv list (no shell) so the empty passphrase
#              `-N ""` survives on every OS. Driven through a shell line, PowerShell DROPS the empty-string
#              arg, ssh-keygen then falls into its interactive passphrase prompt and HANGS, exactly what
#              cost a Windows run six failed attempts and a timeout. argv-direct sidesteps the whole class.
#   wait-access  poll SSH until the freshly pasted key logs in, so the agent detects "done" itself instead
#              of asking the operator to come back and confirm. Timeout -> exit 1 (caller falls back to ask).
# Python 3 stdlib only (no pip). `generate` is local; `wait-access` runs ssh via Bash with
# dangerouslyDisableSandbox:true (it is network), same as the other helpers.
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def out(obj, code=0):
    print(json.dumps(obj))
    sys.exit(code)


def fail(msg, **extra):
    out({"ok": False, "error": msg, **extra}, code=1)


def split_ssh_opts(opts, _nt=None):
    # POSIX shlex eats backslashes, so a Windows key path ("-i C:\Users\me\.ssh\key") would arrive as
    # "C:Usersme.sshkey" (a real onboarding failure). On Windows, tokenize WITHOUT escape processing and
    # strip the surrounding quotes ourselves so backslashes are preserved. _nt is injectable for tests.
    nt = (os.name == "nt") if _nt is None else _nt
    if not opts:
        return []
    if nt:
        toks = shlex.split(opts, posix=False)
        return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t for t in toks]
    return shlex.split(opts)


def cmd_generate(args):
    if not NAME_RE.match(args.name):
        fail(f"invalid --name {args.name!r} (expected a bare filename [A-Za-z0-9._-]+, no path)")
    ssh_dir = Path(args.ssh_dir).expanduser() if args.ssh_dir else Path.home() / ".ssh"
    try:
        ssh_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(ssh_dir, 0o700)
    except OSError as exc:
        fail(f"cannot prepare ssh dir {ssh_dir}: {exc}")
    key = ssh_dir / args.name
    pub = Path(str(key) + ".pub")
    existed = key.exists() and pub.exists()
    if not existed:
        # argv-direct: the empty passphrase "" is a real, separate argv element on every OS here.
        argv = ["ssh-keygen", "-t", "ed25519", "-f", str(key), "-N", "", "-C", args.comment]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=args.timeout)
        except FileNotFoundError:
            fail("ssh-keygen not found on PATH (install OpenSSH client)")
        except subprocess.TimeoutExpired:
            fail("ssh-keygen timed out (interactive prompt? the empty passphrase did not pass through)")
        if proc.returncode != 0 or not pub.exists():
            fail("ssh-keygen failed", exit_code=proc.returncode, stderr=(proc.stderr or "")[-400:])
        try:
            os.chmod(key, 0o600)
        except OSError:
            pass
    try:
        public_key = pub.read_text(encoding="utf-8").strip()
    except OSError as exc:
        fail(f"key generated but cannot read public half: {exc}")
    out({"ok": True, "key_path": str(key), "public_key": public_key, "existed": existed})


def cmd_wait_access(args):
    argv = [
        "ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={args.connect_timeout}",
        "-o", "StrictHostKeyChecking=accept-new", *split_ssh_opts(args.ssh_opts), args.ssh, "echo OK",
    ]
    last = None
    for i in range(args.attempts):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=args.timeout)
        except FileNotFoundError:
            fail("ssh not found on PATH")
        except subprocess.TimeoutExpired:
            proc = None
        if proc is not None and proc.returncode == 0 and "OK" in (proc.stdout or ""):
            out({"ok": True, "reachable": True, "attempt": i + 1})
        if proc is not None:
            last = (proc.stderr or proc.stdout or "").strip()[-200:]
        if i < args.attempts - 1:
            time.sleep(args.interval)
    out(
        {"ok": False, "reachable": False, "attempts": args.attempts, "last_error": last,
         "note": "key not active yet: confirm it is pasted in the VPS panel, or ask the operator"},
        code=1,
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="sshkey.py",
        description="Generate a dedicated ed25519 key (argv-direct, empty passphrase safe on Windows) "
        "and poll SSH access.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    gen = sub.add_parser("generate", help="create ~/.ssh/<name> ed25519 (idempotent) and print the public key")
    gen.add_argument("--name", required=True, help="bare key filename; use the fixed 'fazer-ai-agents' so re-runs reuse the same key (no per-run suffix)")
    gen.add_argument("--comment", default="fazer-ai-onboarding", help="ssh-keygen -C comment")
    gen.add_argument("--ssh-dir", default="", help="override the .ssh dir (default ~/.ssh; for tests)")
    gen.add_argument("--timeout", type=int, default=30)
    gen.set_defaults(fn=cmd_generate)

    wait = sub.add_parser("wait-access", help="poll SSH until the pasted key logs in (else exit 1)")
    wait.add_argument("--ssh", required=True, metavar="USER@HOST")
    wait.add_argument("--ssh-opts", default="", help="extra ssh options, e.g. '-i ~/.ssh/key -p 2222'")
    wait.add_argument("--attempts", type=int, default=30, help="poll attempts (default 30)")
    wait.add_argument("--interval", type=int, default=5, help="seconds between attempts (default 5)")
    wait.add_argument("--connect-timeout", type=int, default=12)
    wait.add_argument("--timeout", type=int, default=20, help="per-attempt ssh timeout")
    wait.set_defaults(fn=cmd_wait_access)

    return parser


def main():
    args = build_parser().parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
