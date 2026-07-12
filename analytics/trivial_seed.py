#!/usr/bin/env python3
"""Seed authentic *trivial* turns for the analytics demo.

Real goal-directed agent traffic (the 12 personas planning trips) contains very few
trivial turns, so the model-selection opportunity looks tiny (~2%). Trivial turns are a
real thing though — greetings, acknowledgements, short confirmations — so this drives the
running app with genuine short messages for the demo users. The orchestrator answers them
directly (no handoff, short output), which is exactly what the trivial heuristic
(handoff_count == 0 AND output_tokens < 60) captures. Re-export the golden seed afterwards
(export_conversations.py) so OptimizationTurns includes them.

These are NOT synthetic OptimizationTurns docs — they are produced by the real agent, so
the tokens/handoff/timeStamp are authentic.

Run against the deployed frontend proxy or a local API:
    python trivial_seed.py --base-url https://<frontend>/api --count 30
"""
from __future__ import annotations

import argparse
import logging
import random
import sys
import time

from data_generator import TravelAppClient

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("trivial_seed")

USERS = [
    "aisha_rahman", "alex_brennan", "david_okafor", "elena_vasquez", "isabelle_dupont",
    "james_mitchell", "jordan_taylor", "marco_rossi", "maya_chen", "priya_sharma",
    "robert_williams", "sarah_johnson",
]

# Short, no-work messages a user actually sends — greetings, acks, confirmations.
TRIVIAL_MESSAGES = [
    "hi", "hello", "hey there", "thanks!", "thank you", "thanks so much", "ok", "okay",
    "sounds good", "great", "perfect", "got it", "cool", "awesome", "yep", "sure",
    "ok thanks", "great, thanks", "that works", "nice", "appreciate it", "makes sense",
]


def run(base_url: str, tenant: str, count: int, delay: float) -> int:
    client = TravelAppClient(base_url)
    if not client.health_check():
        log.error("API not reachable at %s — start the app (or check the deployed URL).", base_url)
        return 1
    sent = 0
    i = 0
    while sent < count:
        user = USERS[i % len(USERS)]
        i += 1
        try:
            session_id = client.create_session(tenant, user)
        except Exception as e:  # noqa: BLE001
            log.error("create_session failed for %s: %s", user, e)
            continue
        # 2-3 trivial messages per fresh session
        for _ in range(random.randint(2, 3)):
            if sent >= count:
                break
            msg = random.choice(TRIVIAL_MESSAGES)
            try:
                client.send_message(tenant, user, session_id, msg)
                sent += 1
                log.info("[%d/%d] %s: %r", sent, count, user, msg)
            except Exception as e:  # noqa: BLE001
                log.error("send failed (%s / %r): %s", user, msg, e)
            time.sleep(delay)
    log.info("done: sent %d trivial messages for tenant %s", sent, tenant)
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed authentic trivial turns via the running app.")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--tenant", default="analytics_demo")
    ap.add_argument("--count", type=int, default=30)
    ap.add_argument("--delay", type=float, default=1.5)
    args = ap.parse_args()
    sys.exit(run(args.base_url, args.tenant, args.count, args.delay))


if __name__ == "__main__":
    main()
