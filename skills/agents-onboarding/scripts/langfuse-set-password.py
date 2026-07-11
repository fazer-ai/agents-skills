#!/usr/bin/env python3
# Reset a self-hosted Langfuse (langfuse/langfuse:3) user's password. BREAK-GLASS, for when the operator
# lost access and cannot change it through the Langfuse UI. Langfuse seeds the initial OWNER via
# LANGFUSE_INIT_USER_* only on first boot (inert afterwards) and has NO env/CLI to rotate the password
# later; the only path is to rewrite the bcrypt hash in the Langfuse Postgres `users.password` column
# (Langfuse verifies with bcryptjs, which accepts the $2b$ prefix Bun emits; cost 12 matches Langfuse's own
# hashing).
#
# This orchestrates the three remote steps over ONE SSH connection, feeding every payload through stdin so
# nothing is hand-assembled on a command line (the footgun remote.py exists to kill: eaten quotes / BOM):
#   1. confirm the schema read-only (`\d users` must have a `password` column),
#   2. bcrypt the new password with the *agents* container's Bun, the fazer.ai agents runtime, always in
#      the stack. Do NOT hash inside the Langfuse container: its bcryptjs lives on an internal pnpm path that
#      `require("bcryptjs")` from /app cannot resolve.
#   3. dry-run by DEFAULT (prints the UPDATE, touches nothing); with --apply, write it to the Langfuse
#      Postgres and confirm `UPDATE 1`.
#
# The new password never touches any process argv (not the local ssh, not the remote docker, not the
# container): it rides an ssh-stdin heredoc straight into the container Bun's stdin. Read it from a 0600
# --password-file or an interactive prompt (never a positional arg, never an env var).
#
# Find the container names with `docker ps` (under Coolify they carry a stack suffix): the *agents* one runs
# harbor…/agents-pro (Bun); the Langfuse Postgres is the `postgres` of the LANGFUSE stack, NOT the agents
# Postgres, NOT coolify-db. Confuse them and you write into the wrong database.
#
# Python 3 stdlib only (no pip). Runs ssh via Bash with dangerouslyDisableSandbox:true (it is network),
# same as remote.py / sshkey.py.
#
# Usage:
#   langfuse-set-password.py --ssh root@HOST --ssh-opts "-i ~/.ssh/key -o IdentitiesOnly=yes" \
#     --agents-container agents-XXXX --langfuse-pg postgres-YYYY --email me@example.com            # dry-run
#   … --password-file ./newpw          # password from a 0600 file (else an interactive prompt)
#   … --apply                          # actually write it (mutation: get the operator's OK first)
import argparse
import getpass
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

# Git Bash/MSYS on Windows reports "/c/Users/..." (or "/mnt/c/..."), which native Python cannot open; match a
# leading drive segment so --password-file can be retranslated to "C:\Users\..." (same as langfuse-verify.py).
MSYS_DRIVE_RE = re.compile(r"^/(?:mnt/)?([A-Za-z])/(.*)$")

# Unique heredoc terminator for the password payload (must never collide with a password line).
PW_EOF = "__LF_PW_EOF_9f13__"

# The bcrypt one-liner, run by the agents container's Bun. Reads the password from stdin (never argv), strips
# the single trailing newline the heredoc adds, emits `$2b$<cost>$…`. No single quotes inside (it is embedded
# in a bash single-quoted string), so nothing here needs escaping.
BUN_HASH_PROG = (
    "const p=await Bun.stdin.text();"
    'process.stdout.write(await Bun.password.hash(p.replace(/\\r?\\n$/,""),'
    '{algorithm:"bcrypt",cost:@@COST@@}))'
)

REMOTE_TMPL = r"""set -uo pipefail
AGENTS=@@AGENTS@@
PG=@@PG@@
SQL_EMAIL=@@SQL_EMAIL@@
APPLY=@@APPLY@@

# 1. Schema (read-only): the users table must carry a `password` column on this Langfuse version.
if docker exec "$PG" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\d users"' 2>/dev/null \
     | grep -qiE '(^| )password '; then
  echo "MARK:SCHEMA_OK"
else
  echo "MARK:SCHEMA_MISSING"
  exit 3
fi

# 2. Hash the new password with the agents container's Bun. The password arrives on this heredoc (part of the
#    ssh-stdin bytes) and is piped into `docker exec -i` stdin, so it is in NO argv anywhere.
HASH=$(docker exec -i "$AGENTS" bun -e '@@BUN_PROG@@' <<'@@PW_EOF@@'
@@PW@@
@@PW_EOF@@
)
if [ -z "$HASH" ]; then echo "MARK:HASH_FAIL"; exit 4; fi
case "$HASH" in
  '$2'*) echo "MARK:HASH_OK" ;;
  *) echo "MARK:HASH_BAD"; printf 'GOT:%s\n' "$HASH"; exit 4 ;;
esac

# Build the UPDATE. $HASH expands to its literal value; the `$` inside a bcrypt hash is NOT re-expanded by
# parameter expansion, and SQL_EMAIL already has its single quotes doubled for the SQL literal.
SQL="UPDATE users SET password='$HASH' WHERE email='$SQL_EMAIL';"
echo "MARK:SQL_BEGIN"
printf '%s\n' "$SQL"
echo "MARK:SQL_END"

if [ "$APPLY" != "1" ]; then
  echo "MARK:DRYRUN"
  exit 0
fi

# 3. Apply (mutation). Feed the SQL via stdin (no `$`-substitution on a command line) to the Langfuse psql.
RES=$(printf '%s\n' "$SQL" | docker exec -i "$PG" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' 2>&1)
echo "MARK:APPLIED"
printf '%s\n' "$RES"
case "$RES" in
  *"UPDATE 1"*) echo "MARK:APPLY_OK" ;;
  *"UPDATE 0"*) echo "MARK:APPLY_NOROW" ;;
  *) echo "MARK:APPLY_UNKNOWN" ;;
esac
"""


def die(msg, **extra):
    print(json.dumps({"ok": False, "error": msg, **extra}))
    sys.exit(1)


def msys_to_native(path):
    m = MSYS_DRIVE_RE.match(path)
    if not m:
        return None
    drive, rest = m.group(1), m.group(2)
    return f"{drive.upper()}:\\" + rest.replace("/", "\\")


def read_password_file(path):
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        native = msys_to_native(path)
        if native is None:
            die(f"cannot read --password-file: {exc}")
        try:
            raw = Path(native).read_text(encoding="utf-8")
        except OSError as exc2:
            die(f"cannot read --password-file (tried {native!r}): {exc2}")
    # A file is expected to hold ONLY the password; drop a single trailing newline, keep everything else.
    return raw[:-1] if raw.endswith("\n") else raw


def resolve_password(args):
    if args.password_file:
        pw = read_password_file(args.password_file)
    elif sys.stdin.isatty():
        pw = getpass.getpass("New Langfuse password: ")
    else:
        die("no password: pass --password-file (0600), or run it in a TTY to be prompted")
    if len(pw) < 8:
        die("password must be at least 8 characters")
    if "\n" in pw or "\r" in pw:
        die("password must not contain a newline")
    if pw.strip() == PW_EOF:
        die("password collides with the internal heredoc terminator; pick another")
    return pw


def bash_squote(s):
    # Wrap s so bash reads it literally inside a single-quoted context.
    return "'" + s.replace("'", "'\\''") + "'"


def build_remote_script(args, password):
    sql_email = args.email.replace("'", "''")  # double single quotes for the SQL literal
    bun_prog = BUN_HASH_PROG.replace("@@COST@@", str(args.cost))
    script = REMOTE_TMPL
    script = script.replace("@@AGENTS@@", bash_squote(args.agents_container))
    script = script.replace("@@PG@@", bash_squote(args.langfuse_pg))
    script = script.replace("@@SQL_EMAIL@@", bash_squote(sql_email))
    script = script.replace("@@APPLY@@", "1" if args.apply else "0")
    script = script.replace("@@BUN_PROG@@", bun_prog)
    script = script.replace("@@PW_EOF@@", PW_EOF)
    # Password LAST, so an inserted value can never be mistaken for another placeholder.
    script = script.replace("@@PW@@", password)
    return script


def run_remote(args, script):
    ssh_cmd = ["ssh"]
    if args.ssh_opts:
        ssh_cmd += shlex.split(args.ssh_opts)
    ssh_cmd += [args.ssh, "bash", "-s"]
    try:
        proc = subprocess.run(
            ssh_cmd,
            input=script.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=args.timeout,
        )
    except FileNotFoundError:
        die("ssh not found on PATH")
    except subprocess.TimeoutExpired:
        die(f"ssh timed out after {args.timeout}s")
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    return proc.returncode, out, err


def parse_result(out):
    marks = [ln[len("MARK:") :] for ln in out.splitlines() if ln.startswith("MARK:")]
    sql = None
    lines = out.splitlines()
    if "SQL_BEGIN" in marks and "SQL_END" in marks:
        i = lines.index("MARK:SQL_BEGIN")
        j = lines.index("MARK:SQL_END")
        sql = "\n".join(lines[i + 1 : j]).strip() or None
    return marks, sql


def main():
    p = argparse.ArgumentParser(
        prog="langfuse-set-password.py",
        description="Break-glass Langfuse password reset (bcrypt via the agents container, applied to the Langfuse Postgres).",
    )
    p.add_argument("--ssh", required=True, metavar="USER@HOST", help="SSH target of the VPS host")
    p.add_argument("--ssh-opts", default="", help='e.g. "-i ~/.ssh/key -o IdentitiesOnly=yes"')
    p.add_argument("--agents-container", required=True, help="name of the agents container (has Bun)")
    p.add_argument("--langfuse-pg", required=True, help="name of the LANGFUSE Postgres container")
    p.add_argument("--email", required=True, help="email of the Langfuse user whose password to reset")
    p.add_argument("--password-file", help="0600 file holding ONLY the new password (else an interactive TTY prompt)")
    p.add_argument("--cost", type=int, default=12, help="bcrypt cost (default 12, matches Langfuse)")
    p.add_argument("--apply", action="store_true", help="write the UPDATE (default: dry-run, prints the SQL)")
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--json", action="store_true", help="emit a JSON result instead of human-readable text")
    args = p.parse_args()

    password = resolve_password(args)
    script = build_remote_script(args, password)
    del password  # not needed past here; keep it out of any later frame

    code, out, err = run_remote(args, script)
    marks, sql = parse_result(out)

    ok = "SCHEMA_OK" in marks and ("HASH_OK" in marks) and (
        "DRYRUN" in marks or "APPLY_OK" in marks
    )
    result = {
        "ok": ok,
        "mode": "apply" if args.apply else "dry-run",
        "email": args.email,
        "schema": "ok" if "SCHEMA_OK" in marks else ("missing" if "SCHEMA_MISSING" in marks else "unknown"),
        "hash": "ok" if "HASH_OK" in marks else ("bad" if "HASH_BAD" in marks else "fail"),
        "applied": ("UPDATE 1" if "APPLY_OK" in marks else ("no-row" if "APPLY_NOROW" in marks else None))
        if args.apply
        else None,
        "sql": sql,
        "ssh_exit": code,
    }
    if err.strip():
        result["stderr"] = err.strip()[:800]

    if args.json:
        print(json.dumps(result))
    else:
        if result["schema"] == "missing":
            print("✗ users.password not found: wrong container, or an unexpected Langfuse schema.")
        elif result["hash"] != "ok":
            print(f"✗ hash step failed ({result['hash']}). stderr:\n{result.get('stderr', '')}")
        elif not args.apply:
            print("● DRY-RUN. Nothing was written. SQL that WOULD be applied:\n")
            print(f"  {sql}\n")
            print("Re-run with --apply (and the operator's OK) to write it. Then log in at /auth/sign-in.")
        elif result["applied"] == "UPDATE 1":
            print(f"✓ Password updated for {args.email}. Log in at /auth/sign-in with the new password.")
        elif result["applied"] == "no-row":
            print(f"✗ No user with email {args.email} (UPDATE 0). Nothing changed.")
        else:
            print(f"? Applied but unexpected psql output. stderr:\n{result.get('stderr', '')}")
            print(f"marks: {marks}")

    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
