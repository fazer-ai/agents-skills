#!/usr/bin/env python3
# Concurrent-customer load simulator for a fazer.ai agents deployment (agents-operation skill).
#
# Drives N simultaneous "customers in service" against a Chatwoot `Channel::Api` inbox that is bound to the
# agent: for each persona it creates a contact + conversation and injects INCOMING messages, exactly like the
# controlled test conversation in references/04-validate-and-apply.md, but many at once. The webhook chain
# (webhook -> debounce -> turn -> real model -> outgoing reply) runs for real, so this exercises the
# production path (including the agent's TOOLS) under concurrency, without any physical device.
#
# MULTI-TURN by default: each persona sends a message, WAITS for the agent's (possibly multi-balloon) reply,
# then sends the next — a real back-and-forth, so every message is its own turn. Pass --burst to instead fire
# all of a persona's messages at once (the debounce-coalescing load test), or --no-poll to fire without
# waiting at all (pure throughput). Realistic contact names (SIM_NAMES) so conversations don't read as fake.
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


def wait_for_reply(cw, conv_id, baseline, timeout, settle):
    """Block until the agent posts a NEW outgoing message (count beyond `baseline`), then let a split
    reply's extra balloons settle before returning. Returns the new outgoing count (== baseline on
    timeout). This is what makes the run MULTI-TURN: we wait for the agent to answer THIS message before
    sending the next, so each message is its own real turn (not coalesced with the others by debounce)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        count = cw.outgoing_count(conv_id)
        if count > baseline:
            # A reply started; a split reply arrives as several balloons over a few seconds, so keep
            # waiting until the count stops growing for `settle` seconds before treating the turn done.
            stable_until = time.time() + settle
            while time.time() < stable_until:
                time.sleep(1)
                newer = cw.outgoing_count(conv_id)
                if newer > count:
                    count = newer
                    stable_until = time.time() + settle
            return count
        time.sleep(2)
    return baseline


def run_persona(cw, inbox_id, index, script, activate_test, think_min, think_max,
                wait_replies, turn_timeout, settle, burst, run_tag, log_lock, detect_timeout):
    base = SIM_NAMES[index % len(SIM_NAMES)]
    cycle = index // len(SIM_NAMES)
    name = base if cycle == 0 else f"{base} {cycle + 1}"
    identifier = f"sim-{run_tag}-{index + 1:02d}"
    result = {"persona": name, "ok": False, "messages_sent": 0, "replies": 0, "turns_answered": 0}

    def log(msg):
        with log_lock:
            print(f"  [{name}] {msg}", file=sys.stderr, flush=True)

    # Deterministic per-persona think time (no RNG): step across [min,max] by index.
    span = max(0.0, think_max - think_min)
    think = think_min + (span * ((index % 5) / 4.0) if span else 0.0)

    try:
        contact_id, source_id = cw.create_contact(inbox_id, name, identifier)
        conv_id = cw.create_conversation(inbox_id, contact_id, source_id)
        result["conversation_id"] = conv_id
        log(f"conversa {conv_id} criada")

        seen = 0
        if activate_test:
            # /teste opts THIS conversation into replies (test mode). Wait for its ack so it lands as its
            # own turn and is not coalesced with the first real message.
            cw.send_incoming(conv_id, "/teste")
            if wait_replies:
                seen = wait_for_reply(cw, conv_id, seen, turn_timeout, settle)
            else:
                time.sleep(think)

        if burst or not wait_replies:
            # Burst mode: fire every message so debounce coalesces them into ~one turn (this is the load
            # test for the debounce/coalescing path, not a multi-turn conversation).
            for content in script:
                cw.send_incoming(conv_id, content)
                result["messages_sent"] += 1
                time.sleep(think)
            if wait_replies:
                final = wait_for_reply(cw, conv_id, seen, turn_timeout, settle)
                result["replies"] = max(0, final - seen)
                result["turns_answered"] = 1 if final > seen else 0
        else:
            # Multi-turn (default): one real turn per message — send, wait for the agent's (possibly
            # multi-balloon) reply, then send the next. Exercises sequential turns per conversation while
            # all personas run concurrently.
            activated = activate_test
            for i, content in enumerate(script):
                time.sleep(think)
                cw.send_incoming(conv_id, content)
                result["messages_sent"] += 1
                # Self-heal a wrong --no-activate-test: on the FIRST message of a not-yet-activated agent,
                # wait only --detect-timeout; persistent silence means the agent is in test mode, so send
                # /teste and resend once. Stops a mis-set flag from causing a silent 0-reply run.
                probe = i == 0 and not activated and detect_timeout > 0
                first_wait = min(detect_timeout, turn_timeout) if probe else turn_timeout
                got = wait_for_reply(cw, conv_id, seen, first_wait, settle)
                if got == seen and probe:
                    log(f"sem resposta em {first_wait:.0f}s — provável modo teste; "
                        "ativando com /teste e reenviando")
                    cw.send_incoming(conv_id, "/teste")
                    seen = max(seen, wait_for_reply(cw, conv_id, seen, turn_timeout, settle))
                    cw.send_incoming(conv_id, content)
                    got = wait_for_reply(cw, conv_id, seen, turn_timeout, settle)
                    activated = True
                if got > seen:
                    result["replies"] += got - seen
                    result["turns_answered"] += 1
                    seen = got
                else:
                    log(f"turno {i + 1}/{len(script)}: sem resposta em {turn_timeout:.0f}s")

        if wait_replies:
            log(f"{result['turns_answered']}/{len(script)} turno(s) respondido(s) "
                f"({result['replies']} balão(ões))")
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
                    help="Do NOT send /teste first (production-mode agent). Self-healing: if the first "
                         "message stays silent for --detect-timeout, /teste is sent automatically anyway")
    ap.add_argument("--min-delay", type=float, default=1.0, help="Min think time before a persona's next message (s)")
    ap.add_argument("--max-delay", type=float, default=4.0, help="Max think time before a persona's next message (s)")
    ap.add_argument("--burst", action="store_true",
                    help="Fire all messages at once (debounce-coalesce test) instead of multi-turn")
    ap.add_argument("--no-poll", dest="wait_replies", action="store_false",
                    help="Do NOT wait for replies (fire only; disables the multi-turn sequencing)")
    ap.add_argument("--poll-timeout", type=float, default=120.0, help="Per-turn seconds to wait for a reply")
    ap.add_argument("--settle", type=float, default=4.0,
                    help="Seconds to let a split reply's extra balloons settle before the next turn")
    ap.add_argument("--detect-timeout", type=float, default=60.0,
                    help="With --no-activate-test: if the first message gets no reply within this many "
                         "seconds, assume the agent is in test mode, send /teste and resend once "
                         "(self-heals a wrong --no-activate-test). 0 disables the auto-heal")
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
    mode = "burst" if args.burst else ("multi-turno" if args.wait_replies else "fire-only")
    print(
        f"Simulando {args.count} cliente(s) concorrente(s) no inbox {args.inbox_id} "
        f"(conta {args.account_id}); modo={mode}; activate-test={args.activate_test}",
        file=sys.stderr,
        flush=True,
    )

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.count) as pool:
        futures = [
            pool.submit(
                run_persona, cw, args.inbox_id, i, scripts[i % len(scripts)],
                args.activate_test, args.min_delay, args.max_delay,
                args.wait_replies, args.poll_timeout, args.settle, args.burst,
                args.run_tag, log_lock, args.detect_timeout,
            )
            for i in range(args.count)
        ]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    results.sort(key=lambda r: r["persona"])
    ok = sum(1 for r in results if r["ok"])
    replied = sum(1 for r in results if r.get("turns_answered", 0) > 0)
    total_turns = sum(len(scripts[i % len(scripts)]) for i in range(args.count))
    answered_turns = sum(r.get("turns_answered", 0) for r in results)
    summary = {
        "requested": args.count,
        "succeeded": ok,
        "with_reply": replied,
        "mode": mode,
        "messages_sent": sum(r["messages_sent"] for r in results),
        "turns_answered": answered_turns,
        "turns_total": total_turns,
        "results": results,
    }
    print("RESULT_JSON:" + json.dumps(summary, ensure_ascii=False))
    turns_note = (
        f"; {answered_turns}/{total_turns} turno(s) respondido(s)" if args.wait_replies else ""
    )
    print(
        f"\n{ok}/{args.count} conversa(s) OK; {replied} com resposta do agente{turns_note}. "
        f"Confira o USO DAS FERRAMENTAS no /logs (ExecutionLog) e no Langfuse; "
        f"as conversas aparecem no Chatwoot na conta {args.account_id}.",
        file=sys.stderr,
    )
    if args.wait_replies and answered_turns == 0:
        print(
            "AVISO: zero respostas em todas as conversas. O modo teste é contornado automaticamente "
            "(auto /teste no multi-turno), então isto aponta OUTRA causa: agente desabilitado, sem "
            "modelo/credencial configurada, ou o Agent Bot não está atribuído a este inbox. "
            "Cheque o /logs do agente.",
            file=sys.stderr,
        )
    # Non-zero exit if any persona failed, so callers/CI can gate on it.
    sys.exit(0 if ok == args.count else 1)


if __name__ == "__main__":
    main()
