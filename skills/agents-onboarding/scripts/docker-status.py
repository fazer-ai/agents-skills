#!/usr/bin/env python3
# Docker status helper for the fazer.ai agents onboarding. ONE job: read container status over SSH without
# the agent hand-quoting a `docker ps --format '{{...}}\t'` line. Driven through PowerShell->SSH, that line
# gets MANGLED: the `{{...}}` braces and the `\t` are eaten/rewritten, so the agent improvises a broken
# command and misreads "nothing running" (a real Windows-run footgun). This helper OWNS the format string
# and runs ssh with a DIRECT argv list (no local shell), so the braces reach the remote shell intact, same
# payload-owning pattern the other helpers use. Output is normalized JSON the agent parses.
#
#   docker-status.py --ssh root@HOST                      # `docker ps`           (running containers)
#   docker-status.py --ssh root@HOST --all               # `docker ps -a`        (include stopped)
#   docker-status.py --ssh root@HOST --project <uuid>    # `docker compose -p <uuid> ps` (a Coolify service)
#
# Python 3 stdlib only (no pip). Runs ssh via Bash with dangerouslyDisableSandbox:true (it is network),
# same as sshkey.py wait-access. --dry-run prints the exact argv + remote command without connecting.
import argparse
import json
import os
import shlex
import subprocess
import sys

# Project/compose name is interpolated into the remote command, so keep it to a safe bare token.
SAFE_TOKEN = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")


def out(obj, code=0):
    print(json.dumps(obj))
    sys.exit(code)


def fail(msg, **extra):
    out({"ok": False, "error": msg, **extra}, code=1)


def split_ssh_opts(opts, _nt=None):
    # POSIX shlex eats backslashes, so a Windows key path ("-i C:\Users\me\.ssh\key") would arrive as
    # "C:Usersme.sshkey". On Windows, tokenize WITHOUT escape processing and strip the surrounding quotes
    # ourselves so backslashes survive. _nt is injectable for tests. (Kept in sync with sshkey.py.)
    nt = (os.name == "nt") if _nt is None else _nt
    if not opts:
        return []
    if nt:
        toks = shlex.split(opts, posix=False)
        return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t for t in toks]
    return shlex.split(opts)


def remote_command(args):
    # The helper owns these strings; the agent never types braces. `{{json .}}` emits one JSON object per
    # line on `docker ps`; compose `--format json` emits an array or NDJSON depending on the v2 version.
    if args.project:
        if any(c not in SAFE_TOKEN for c in args.project):
            fail(f"invalid --project {args.project!r} (expected a bare [A-Za-z0-9._-] token)")
        return f"docker compose -p {args.project} ps --format json"
    flag = "-a " if args.all else ""
    return f"docker ps {flag}--format '{{{{json .}}}}'"


def parse_json_output(text):
    text = text.strip()
    if not text:
        return []
    # Compose may print a single JSON array/object; `docker ps` prints NDJSON. Try whole-doc first.
    try:
        doc = json.loads(text)
        return doc if isinstance(doc, list) else [doc]
    except json.JSONDecodeError:
        pass
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"_unparsed": line})
    return rows


def cmd_status(args):
    remote = remote_command(args)
    argv = [
        "ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={args.connect_timeout}",
        "-o", "StrictHostKeyChecking=accept-new", *split_ssh_opts(args.ssh_opts), args.ssh, remote,
    ]
    if args.dry_run:
        out({"ok": True, "dry_run": True, "remote_cmd": remote, "argv": argv})
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=args.timeout)
    except FileNotFoundError:
        fail("ssh not found on PATH")
    except subprocess.TimeoutExpired:
        fail("ssh timed out", remote_cmd=remote)
    if proc.returncode != 0:
        fail(
            "ssh/docker command failed",
            exit_code=proc.returncode,
            remote_cmd=remote,
            stderr=(proc.stderr or "").strip()[-400:],
        )
    containers = parse_json_output(proc.stdout)
    out({"ok": True, "remote_cmd": remote, "count": len(containers), "containers": containers})


def build_parser():
    parser = argparse.ArgumentParser(
        prog="docker-status.py",
        description="Read container status over SSH (payload-owning; survives PowerShell->SSH). "
        "Normalizes `docker ps` / `docker compose ps` output to JSON.",
    )
    parser.add_argument("--ssh", required=True, metavar="USER@HOST")
    parser.add_argument("--ssh-opts", default="", help="extra ssh options, e.g. '-i ~/.ssh/key -p 2222'")
    parser.add_argument("--project", default="", help="a compose project (Coolify service uuid): docker compose -p <p> ps")
    parser.add_argument("--all", action="store_true", help="include stopped containers (docker ps -a)")
    parser.add_argument("--connect-timeout", type=int, default=12)
    parser.add_argument("--timeout", type=int, default=25, help="ssh timeout (seconds)")
    parser.add_argument("--dry-run", action="store_true", help="print the argv + remote command, do not connect")
    parser.set_defaults(fn=cmd_status)
    return parser


def main():
    args = build_parser().parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
