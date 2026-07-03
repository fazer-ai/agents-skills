#!/usr/bin/env python3
# Langfuse ingestion smoke test for the fazer.ai agents onboarding. POSTs a tiny batch to
# /api/public/ingestion with HTTP Basic auth and asserts 207/200, NOT 500. This is the load-bearing
# check: a naive "test connection" hits /api/public/projects, which reads only Postgres and returns 200
# even when blob storage (MinIO/S3) is missing, masking a broken ingestion that silently drops every
# trace. The Langfuse keys come from --keys-file (JSON {publicKey, secretKey}); the secret key never
# touches argv. Python 3 stdlib only.
import argparse
import base64
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Git Bash/MSYS on Windows reports paths as "/c/Users/..." (or "/mnt/c/..." under WSL), but native Python on
# Windows cannot open those: it needs "C:\Users\...". Match a leading drive segment so we can retranslate.
MSYS_DRIVE_RE = re.compile(r"^/(?:mnt/)?([A-Za-z])/(.*)$")

BATCH = {
    "batch": [
        {
            "id": "verify-1",
            "type": "trace-create",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "body": {"id": "verify-1", "name": "onboarding-verify"},
        }
    ]
}


def out(obj, code=0):
    print(json.dumps(obj))
    sys.exit(code)


def fail(msg, **extra):
    out({"ok": False, "error": msg, **extra}, code=1)


def msys_to_native(path):
    # Translate a Git Bash/MSYS/WSL path ("/c/Users/me/x", "/mnt/c/Users/me/x") to the native Windows form
    # ("C:\Users\me\x") so open() finds it. Returns None when the path is not drive-prefixed (nothing to
    # translate). POSIX paths and already-native Windows paths ("C:\...", "C:/...") are left to open() as-is.
    m = MSYS_DRIVE_RE.match(path)
    if not m:
        return None
    drive, rest = m.group(1), m.group(2)
    return f"{drive.upper()}:\\" + rest.replace("/", "\\")


def read_text_file(path, what):
    # Read a UTF-8 text file, retrying a Git Bash/MSYS path ("/c/Users/me/x") as its native Windows form when
    # the first open fails (same footgun as remote.py's --script-file). `what` names the flag for the error.
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        native = msys_to_native(path)
        if native is None:
            fail(f"cannot read {what}: {exc}")
        try:
            return Path(native).read_text(encoding="utf-8")
        except OSError as exc2:
            fail(f"cannot read {what} (tried {native!r}): {exc2}")


def cmd_ingestion(args):
    try:
        keys = json.loads(read_text_file(args.keys_file, "--keys-file"))
    except ValueError as exc:
        fail(f"--keys-file is not valid JSON (expects {{publicKey, secretKey}}): {exc}")
    public_key, secret_key = keys.get("publicKey"), keys.get("secretKey")
    if not public_key or not secret_key:
        fail("--keys-file must hold both publicKey and secretKey")
    url = args.base_url.rstrip("/") + "/api/public/ingestion"
    auth = base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        url,
        data=json.dumps(BATCH).encode("utf-8"),
        method="POST",
        headers={"Authorization": "Basic " + auth, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            status, raw = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        fail(f"request failed: {exc.reason}", url=url)
    ok = status in (200, 207)
    result = {"ok": ok, "status": status, "expected": "207/200", "body": raw[:300]}
    if not ok:
        result["hint"] = "500 usually means missing MinIO/S3 blob storage (LANGFUSE_S3_* empty); traces are dropped"
    out(result, code=0 if ok else 1)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="langfuse-verify.py",
        description="Verify Langfuse ingestion actually works (207/200, not the masked 500).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingestion", help="POST a tiny batch to /api/public/ingestion and assert 207/200")
    ing.add_argument("--base-url", required=True, metavar="URL", help="e.g. https://langfuse.example.com:3000")
    ing.add_argument("--keys-file", required=True, help="JSON file with {publicKey, secretKey} (chmod 600)")
    ing.add_argument("--timeout", type=int, default=30)
    ing.set_defaults(fn=cmd_ingestion)
    return parser


def main():
    args = build_parser().parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
