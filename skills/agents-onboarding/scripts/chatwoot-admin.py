#!/usr/bin/env python3
# Chatwoot admin access-token reader for the fazer.ai agents onboarding. The USER creates the first admin in
# the Chatwoot onboarding screen (account gate); this reads that admin by email and returns its API access
# token; it never creates an account or user. Runs a Rails runner INSIDE the Chatwoot container over SSH,
# base64-piped so the script's own quotes never hit a shell.
#
# Output: the admin api_access_token is written to a 0600 file; only metadata is printed. The token is what
# agents deployment_connect + the Inbox API need. Works on any tier (Coolify, Portainer or plain compose).
# Python 3 stdlib only (no pip). Network/SSH runs via Bash with dangerouslyDisableSandbox:true (00-prereqs).
import argparse
import base64
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

CONTAINER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# The email arrives base64-decoded in-container so accents/spaces can't break quoting. RESULT_JSON: marks
# the line we parse. This READS the admin the user already created (account gate); it never creates one.
RUBY_PROVISION = r'''
require 'base64'; require 'json'
result =
  begin
    email = Base64.strict_decode64("__B64_EMAIL__").force_encoding("UTF-8")
    u = User.find_by(email: email)
    if u.nil?
      { "error" => "no Chatwoot user with email #{email}: create the admin in the Chatwoot onboarding screen first, then re-run" }
    else
      acc = u.accounts.order(:id).first
      if acc.nil?
        { "error" => "Chatwoot user #{email} belongs to no account yet (finish the Chatwoot onboarding first)" }
      else
        # The polymorphic AccessToken (owner = the user) is the stable interface across images, whether or
        # not a given image still exposes User#access_token. Idempotent: find_or_create_by! reuses the
        # user's existing token (the model's before-create hook fills a freshly minted one).
        at = AccessToken.find_or_create_by!(owner: u)
        { "account_id" => acc.id, "user_id" => u.id, "email" => email, "token" => at.token }
      end
    end
  rescue => e
    { "error" => "#{e.class}: #{e.message}" }
  end
puts "RESULT_JSON:" + JSON.generate(result)
'''

# Re-runs the fazer.ai "check new versions" job so the hub-side subscription (Kanban/Pro) registers, then
# reports the subscription config key NAMES present (+ any *status* values); never dumps raw config values,
# which could hold a secret. jitter_applied:true is mandatory (else the job only reschedules, no sync).
RUBY_REFRESH = r'''
require 'json'
Internal::CheckNewVersionsJob.perform_now(jitter_applied: true)
names = InstallationConfig.where("name ILIKE '%subscription%' OR name ILIKE 'fazer%'").pluck(:name)
diag = {}
%w[FAZER_AI_SUBSCRIPTION_SYNC_ERROR_MESSAGE FAZER_AI_SUBSCRIPTION_VERIFIED_AT].each { |k| diag[k] = InstallationConfig.find_by(name: k)&.value }
puts "RESULT_JSON:" + JSON.generate({"refreshed" => true, "config_keys" => names, "diagnostics" => diag})
'''

# Lê a identidade da instância que o hub usa pra casar (host = FRONTEND_URL; identifier = UUID de
# instalação do Chatwoot quando existe). É o input do `agents hub create-instance --identifier <host>`
# / attach-license, sem precisar do hub MCP no agente. Read-only.
RUBY_INSTALLATION_ID = r'''
require 'json'
ident = (InstallationConfig.find_by(name: 'INSTALLATION_IDENTIFIER')&.value rescue nil)
host = ENV['FRONTEND_URL']
host = (InstallationConfig.find_by(name: 'FRONTEND_URL')&.value rescue nil) if host.nil? || host.to_s.strip.empty?
puts "RESULT_JSON:" + JSON.generate({"installation_identifier" => ident, "frontend_url" => host})
'''


def out(obj, code=0):
    print(json.dumps(obj))
    sys.exit(code)


def fail(msg, **extra):
    out({"ok": False, "error": msg, **extra}, code=1)


def b64_pipe(payload, target):
    blob = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    return f"echo '{blob}' | base64 -d | {target}"


def split_ssh_opts(opts, _nt=None):
    # POSIX shlex eats backslashes, mangling a Windows key path ("-i C:\Users\me\.ssh\key" ->
    # "C:Usersme.sshkey"). On Windows, tokenize without escape processing and strip our own quotes so the
    # backslashes survive. _nt is injectable for tests.
    nt = (os.name == "nt") if _nt is None else _nt
    if not opts:
        return []
    if nt:
        toks = shlex.split(opts, posix=False)
        return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t for t in toks]
    return shlex.split(opts)


def run_ssh(dest, ssh_opts, remote_cmd, timeout):
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", *split_ssh_opts(ssh_opts), dest, remote_cmd]
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        fail("ssh not found on PATH")
    except subprocess.TimeoutExpired:
        fail(f"ssh timed out after {timeout}s", dest=dest)


def cmd_provision(args):
    if not CONTAINER_RE.match(args.container):
        fail(f"invalid --container {args.container!r} (expected [A-Za-z0-9_.-]+)")
    if "@" not in args.email:
        fail("--email must be an email address")
    ruby = RUBY_PROVISION.replace(
        "__B64_EMAIL__", base64.b64encode(args.email.encode("utf-8")).decode("ascii")
    )
    target = f"docker exec -i {args.container} bundle exec rails runner -"
    proc = run_ssh(args.ssh, args.ssh_opts, b64_pipe(ruby, target), args.timeout)
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    match = re.search(r"RESULT_JSON:(\{.*\})", combined)
    if not match:
        fail(
            "Rails runner returned no result (is --container the Chatwoot rails container?)",
            exit_code=proc.returncode,
            stdout=(proc.stdout or "")[-600:],
            stderr=(proc.stderr or "")[-600:],
        )
    try:
        data = json.loads(match.group(1))
    except ValueError:
        fail("could not parse RESULT_JSON", raw=match.group(1)[:200])
    # The runner emits a deliberate {"error": …} when the admin does not exist yet (the user must create
    # it in the Chatwoot UI first). Surface THAT, not the generic "no result": it tells the agent to wait.
    if data.get("error"):
        fail(data["error"])
    dest = Path(args.out)
    dest.write_text(
        json.dumps(
            {
                "account_id": data["account_id"],
                "user_id": data["user_id"],
                "email": data["email"],
                "api_access_token": data["token"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        dest.chmod(0o600)
    except OSError:
        pass
    out(
        {
            "ok": True,
            "out_file": str(dest),
            "account_id": data["account_id"],
            "user_id": data["user_id"],
            "email": data["email"],
            "note": "api_access_token written to file (chmod 600), not printed",
        }
    )


def cmd_refresh_subscription(args):
    if not CONTAINER_RE.match(args.container):
        fail(f"invalid --container {args.container!r} (expected [A-Za-z0-9_.-]+)")
    target = f"docker exec -i {args.container} bundle exec rails runner -"
    proc = run_ssh(args.ssh, args.ssh_opts, b64_pipe(RUBY_REFRESH, target), args.timeout)
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    match = re.search(r"RESULT_JSON:(\{.*\})", combined)
    if not match:
        fail(
            "Rails runner returned no result (is --container the Chatwoot rails container?)",
            exit_code=proc.returncode,
            stdout=(proc.stdout or "")[-600:],
            stderr=(proc.stderr or "")[-600:],
        )
    try:
        data = json.loads(match.group(1))
    except ValueError:
        fail("could not parse RESULT_JSON", raw=match.group(1)[:200])
    out({"ok": True, **data})


def cmd_installation_id(args):
    if not CONTAINER_RE.match(args.container):
        fail(f"invalid --container {args.container!r} (expected [A-Za-z0-9_.-]+)")
    target = f"docker exec -i {args.container} bundle exec rails runner -"
    proc = run_ssh(args.ssh, args.ssh_opts, b64_pipe(RUBY_INSTALLATION_ID, target), args.timeout)
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    match = re.search(r"RESULT_JSON:(\{.*\})", combined)
    if not match:
        fail(
            "Rails runner returned no result (is --container the Chatwoot rails container?)",
            exit_code=proc.returncode,
            stdout=(proc.stdout or "")[-600:],
            stderr=(proc.stderr or "")[-600:],
        )
    try:
        data = json.loads(match.group(1))
    except ValueError:
        fail("could not parse RESULT_JSON", raw=match.group(1)[:200])
    out({"ok": True, **data})


def build_parser():
    parser = argparse.ArgumentParser(
        prog="chatwoot-admin.py",
        description="Chatwoot admin/account/token + subscription refresh via a Rails runner over SSH.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    ssh = argparse.ArgumentParser(add_help=False)
    ssh.add_argument("--ssh", required=True, metavar="USER@HOST", help="SSH destination, e.g. root@1.2.3.4")
    ssh.add_argument("--container", required=True, help="Chatwoot rails container (from docker ps)")
    ssh.add_argument("--ssh-opts", default="", help="extra ssh options, e.g. '-i ~/.ssh/key -p 2222'")
    ssh.add_argument("--timeout", type=int, default=180)

    prov = sub.add_parser("provision", parents=[ssh], help="read the admin (by email) the user created + return its API token")
    prov.add_argument("--email", required=True, help="email of the admin the user created in the Chatwoot UI")
    prov.add_argument("--out", required=True, help="file to write the api_access_token to (chmod 600)")
    prov.set_defaults(fn=cmd_provision)

    refresh = sub.add_parser(
        "refresh-subscription", parents=[ssh], help="run the fazer.ai Refresh job + report subscription config"
    )
    refresh.set_defaults(fn=cmd_refresh_subscription)

    idcmd = sub.add_parser(
        "installation-id", parents=[ssh], help="read the instance identity the hub matches (host + uuid)"
    )
    idcmd.set_defaults(fn=cmd_installation_id)

    return parser


def main():
    args = build_parser().parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
