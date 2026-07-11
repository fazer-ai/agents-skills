#!/usr/bin/env python3
# Concurrent-customer load simulator for a fazer.ai agents deployment (agents-operation skill).
#
# Drives N simultaneous "customers in service" against a Chatwoot `Channel::Api` inbox that is bound to the
# agent: for each persona it creates a contact + conversation and injects INCOMING messages, exactly like the
# controlled test conversation in references/04-validate-and-apply.md, but many at once. The webhook chain
# (webhook -> debounce -> turn -> real model -> outgoing reply) runs for real, so this exercises the
# production path (including the agent's TOOLS) under concurrency, without any physical device.
#
# Bypassing /teste: an agent in `mode: "test"` stays silent in a conversation until the customer sends
# `/teste` (which stamps `testActivatedAt` for THAT conversation). So by default this sends `/teste` as the
# first message of each simulated conversation, which "contorna" test mode WITHOUT flipping the real agent to
# production (each conversation opts itself in). Pass --no-activate-test to skip it (e.g. a production agent,
# which already answers).
#
# Testing the TOOLS: the default message scripts are written to PROVOKE common tools (scheduling, payment
# link, availability/FAQ). For a specific agent, pass --script with messages tailored to that agent's tool
# list (see references/05-load-sim.md).
#
# Python 3 stdlib only (no pip). Network runs via Bash with dangerouslyDisableSandbox:true (see the skill's
# 00-production-safety.md). This ONLY writes to Chatwoot (incoming messages on a TEST inbox); point it at a
# test inbox, never a real customer's conversation.

import argparse
import concurrent.futures
import json
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# Default per-persona message scripts. Each inner list is one conversation's messages, sent in order. They are
# written to trigger the agent's tools (scheduling, payment, availability/FAQ) so the run actually tests the
# tools, not just chit-chat. Personas cycle through these (varied so they are not all identical). Override the
# whole set with --script <file.json> (a JSON array of arrays of strings) for a specific agent.
DEFAULT_SCRIPTS = [
    [
        "Oi! Queria marcar um horário pra amanhã de tarde, pode ser?",
        "Qual o horário mais cedo que tem disponível?",
        "Fechado, pode agendar esse. Obrigado!",
    ],
    [
        "Bom dia, quanto custa a consulta?",
        "Consegue me mandar o link de pagamento por PIX?",
        "Perfeito, já vou pagar.",
    ],
    [
        "Vocês atendem no sábado? Qual o horário de funcionamento?",
        "E ficam abertos no feriado da semana que vem?",
        "Entendi, valeu pela info!",
    ],
    [
        "Preciso remarcar o meu horário, dá pra mudar pra quinta?",
        "Pode ser de manhã?",
        "Show, obrigado!",
    ],
    [
        "Oi, queria tirar uma dúvida sobre os serviços de vocês.",
        "Vocês fazem atendimento a domicílio? Quanto fica?",
        "Legal, e como faço pra agendar?",
    ],
]

# Realistic contact names (so the simulated conversations read like real customers in Chatwoot, not
# "Sim Cliente 01"). Picked deterministically by index; the unique key stays the identifier, so names
# may repeat past the list length (a numeric suffix keeps them distinct without looking robotic).
SIM_NAMES = [
    "Ana Beatriz Ribeiro", "Carlos Eduardo Nunes", "Mariana Oliveira",
    "João Pedro Santos", "Fernanda Lima", "Rafael Almeida",
    "Juliana Costa", "Bruno Carvalho", "Patrícia Souza",
    "Lucas Martins", "Camila Rodrigues", "Thiago Ferreira",
    "Larissa Gomes", "Gustavo Barbosa", "Beatriz Cardoso",
    "Rodrigo Pereira", "Amanda Rocha", "Felipe Araújo",
    "Isabela Ramos", "Marcelo Dias", "Vanessa Correia",
    "Diego Teixeira", "Natália Freitas", "Leonardo Pinto",
]


class Chatwoot:
    """Thin Chatwoot Application API client (api_access_token auth), stdlib-only."""

    def __init__(self, base_url, token, account_id, insecure=False):
        self.base = base_url.rstrip("/")
        self.token = token
        self.account_id = account_id
        self.ctx = ssl._create_unverified_context() if insecure else None

    def _req(self, method, path, body=None):
        url = f"{self.base}/api/v1/accounts/{self.account_id}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("api_access_token", self.token)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(f"{method} {path} -> {e.reason}") from None

    def create_contact(self, inbox_id, name, identifier):
        # Creating a contact with inbox_id auto-creates a contact_inbox and returns its source_id. Shapes vary
        # across Chatwoot versions, so extract the source_id defensively and fall back to an explicit
        # contact_inbox create if it is absent.
        res = self._req(
            "POST",
            "/contacts",
            {"inbox_id": inbox_id, "name": name, "identifier": identifier},
        )
        payload = res.get("payload", res)
        contact = payload.get("contact", payload)
        contact_id = contact.get("id")
        source_id = None
        ci = payload.get("contact_inbox") or {}
        if isinstance(ci, dict):
            source_id = ci.get("source_id")
        if not source_id:
            for entry in contact.get("contact_inboxes", []) or []:
                inbox = entry.get("inbox") or {}
                if inbox.get("id") == inbox_id or source_id is None:
                    source_id = entry.get("source_id")
        if not source_id:
            ci = self._req(
                "POST", f"/contacts/{contact_id}/contact_inboxes", {"inbox_id": inbox_id}
            )
            source_id = ci.get("source_id")
        if not source_id:
            raise RuntimeError("could not obtain a source_id for the contact/inbox")
        return contact_id, source_id

    def create_conversation(self, inbox_id, contact_id, source_id):
        res = self._req(
            "POST",
            "/conversations",
            {"inbox_id": inbox_id, "contact_id": contact_id, "source_id": source_id},
        )
        conv_id = res.get("id") or (res.get("payload") or {}).get("id")
        if not conv_id:
            raise RuntimeError(f"conversation create returned no id: {res}")
        return conv_id

    def send_incoming(self, conv_id, content):
        return self._req(
            "POST",
            f"/conversations/{conv_id}/messages",
            {"content": content, "message_type": "incoming"},
        )

    def outgoing_count(self, conv_id):
        res = self._req("GET", f"/conversations/{conv_id}/messages")
        msgs = res.get("payload", res if isinstance(res, list) else [])
        # message_type 1 == outgoing (agent/agent-bot reply); private notes are excluded.
        return sum(
            1
            for m in msgs
            if (m.get("message_type") in (1, "outgoing"))
            and not m.get("private")
        )


def run_persona(cw, inbox_id, index, script, activate_test, min_delay, max_delay,
                poll_replies, poll_timeout, run_tag, log_lock):
    base = SIM_NAMES[index % len(SIM_NAMES)]
    cycle = index // len(SIM_NAMES)
    name = base if cycle == 0 else f"{base} {cycle + 1}"
    identifier = f"sim-{run_tag}-{index + 1:02d}"
    result = {"persona": name, "ok": False, "messages_sent": 0, "replies": 0}

    def log(msg):
        with log_lock:
            print(f"  [{name}] {msg}", file=sys.stderr, flush=True)

    try:
        contact_id, source_id = cw.create_contact(inbox_id, name, identifier)
        conv_id = cw.create_conversation(inbox_id, contact_id, source_id)
        result["conversation_id"] = conv_id
        log(f"conversa {conv_id} criada")

        if activate_test:
            # Opt this conversation into responses even if the agent is in test mode.
            cw.send_incoming(conv_id, "/teste")
            time.sleep(min_delay)

        # Deterministic per-persona spread of the send delay (no RNG): step across [min,max] by index.
        span = max(0.0, max_delay - min_delay)
        delay = min_delay + (span * ((index % 5) / 4.0) if span else 0.0)
        for content in script:
            cw.send_incoming(conv_id, content)
            result["messages_sent"] += 1
            time.sleep(delay)

        if poll_replies:
            deadline = time.time() + poll_timeout
            while time.time() < deadline:
                replies = cw.outgoing_count(conv_id)
                if replies > 0:
                    result["replies"] = replies
                    break
                time.sleep(2)
            else:
                result["replies"] = cw.outgoing_count(conv_id)
            log(f"{result['replies']} resposta(s) do agente observada(s)")

        result["ok"] = True
    except Exception as e:  # noqa: BLE001 - one persona failing must not kill the run
        result["error"] = str(e)
        log(f"ERRO: {e}")
    return result


def main():
    ap = argparse.ArgumentParser(
        description="Simulate N concurrent customers against a Chatwoot Api inbox bound to the agent."
    )
    ap.add_argument("--base-url", required=True, help="Chatwoot base URL (e.g. https://chatwoot.example.com)")
    tok = ap.add_mutually_exclusive_group(required=True)
    tok.add_argument("--token", help="Chatwoot admin api_access_token")
    tok.add_argument("--token-file", help="File containing the api_access_token (0600)")
    ap.add_argument("--account-id", required=True, type=int, help="Chatwoot account id")
    ap.add_argument("--inbox-id", required=True, type=int, help="Api-channel inbox id (bound to the agent)")
    ap.add_argument("--count", type=int, default=15, help="Number of concurrent customers (default 15)")
    ap.add_argument("--script", help="JSON file: array of arrays of strings (per-persona message scripts)")
    ap.add_argument("--no-activate-test", dest="activate_test", action="store_false",
                    help="Do NOT send /teste first (use for a production-mode agent)")
    ap.add_argument("--min-delay", type=float, default=1.0, help="Min seconds between a persona's messages")
    ap.add_argument("--max-delay", type=float, default=4.0, help="Max seconds between a persona's messages")
    ap.add_argument("--no-poll", dest="poll_replies", action="store_false",
                    help="Do NOT poll for agent replies (just fire messages)")
    ap.add_argument("--poll-timeout", type=float, default=60.0, help="Seconds to wait for a reply per persona")
    ap.add_argument("--run-tag", default=str(int(time.time())), help="Tag appended to contact identifiers")
    ap.add_argument("--insecure", action="store_true", help="Skip TLS verification (staging/self-signed)")
    args = ap.parse_args()

    token = args.token
    if args.token_file:
        token = Path(args.token_file).read_text(encoding="utf-8").strip()
    if not token:
        ap.error("empty token")

    scripts = DEFAULT_SCRIPTS
    if args.script:
        scripts = json.loads(Path(args.script).read_text(encoding="utf-8"))
        if not (isinstance(scripts, list) and scripts and all(isinstance(s, list) for s in scripts)):
            ap.error("--script must be a JSON array of arrays of strings")

    cw = Chatwoot(args.base_url, token, args.account_id, insecure=args.insecure)
    log_lock = threading.Lock()
    print(
        f"Simulando {args.count} cliente(s) concorrente(s) no inbox {args.inbox_id} "
        f"(conta {args.account_id}); activate-test={args.activate_test}",
        file=sys.stderr,
        flush=True,
    )

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.count) as pool:
        futures = [
            pool.submit(
                run_persona, cw, args.inbox_id, i, scripts[i % len(scripts)],
                args.activate_test, args.min_delay, args.max_delay,
                args.poll_replies, args.poll_timeout, args.run_tag, log_lock,
            )
            for i in range(args.count)
        ]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    results.sort(key=lambda r: r["persona"])
    ok = sum(1 for r in results if r["ok"])
    replied = sum(1 for r in results if r.get("replies", 0) > 0)
    summary = {
        "requested": args.count,
        "succeeded": ok,
        "with_reply": replied,
        "messages_sent": sum(r["messages_sent"] for r in results),
        "results": results,
    }
    print("RESULT_JSON:" + json.dumps(summary, ensure_ascii=False))
    print(
        f"\n{ok}/{args.count} conversa(s) OK; {replied} com resposta do agente. "
        f"Confira o USO DAS FERRAMENTAS no /logs (ExecutionLog) e no Langfuse; "
        f"as conversas aparecem no Chatwoot na conta {args.account_id}.",
        file=sys.stderr,
    )
    # Non-zero exit if any persona failed, so callers/CI can gate on it.
    sys.exit(0 if ok == args.count else 1)


if __name__ == "__main__":
    main()
