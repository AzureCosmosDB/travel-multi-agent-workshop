"""
Data Enrichment Script for the Travel Multi-Agent Application.

Adds preference-conflict conversations to existing users to trigger memory
supersession. Run this AFTER data_generator.py to create analytics-interesting
patterns where users change their minds and the AI updates its understanding.

The data_generator.py already includes some conflicts (Maya: vegan->pescatarian,
Alex: pescatarian->vegetarian, James: luxury->boutique, Priya: shellfish allergy).
This script adds MORE conflicts for the remaining users.

Usage:
    python data_enricher.py                    # Run all conflicts
    python data_enricher.py --dry-run          # Preview without API calls
    python data_enricher.py --delay 5          # Slower pace
"""

import argparse
import json
import logging
import sys
import time

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("enricher")

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TENANT = "analytics_demo"
DEFAULT_DELAY = 3


class TravelAppClient:
    def __init__(self, base_url, timeout=300):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout)

    def health_check(self):
        try:
            r = self.client.get(f"{self.base_url}/health")
            return r.status_code == 200
        except httpx.ConnectError:
            return False

    def create_session(self, tenant_id, user_id):
        url = f"{self.base_url}/tenant/{tenant_id}/user/{user_id}/sessions"
        r = self.client.post(url, params={"activeAgent": "orchestrator"})
        r.raise_for_status()
        data = r.json()
        return data.get("sessionId") or data.get("id")

    def send_message(self, tenant_id, user_id, session_id, message):
        url = (
            f"{self.base_url}/tenant/{tenant_id}/user/{user_id}"
            f"/sessions/{session_id}/completion"
        )
        r = self.client.post(
            url,
            content=json.dumps(message),
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return r.json()

    def close(self):
        self.client.close()


# ============================================================================
# Conflict conversations -- trigger memory supersession
# These contradict preferences established by the data_generator.
# ============================================================================

CONFLICT_CONVOS = {
    "sarah_johnson": [
        "Update: my daughter is no longer gluten-free, the doctor cleared her. Regular restaurants are fine now.",
        "Also, we do not need wheelchair access anymore. My mother will not be joining us.",
        "We prefer adventure activities now over museums. The kids are older and want thrills.",
        "Budget has changed too. We want luxury family resorts now, not budget hotels.",
    ],
    "david_okafor": [
        "Hey, I have switched to a plant-based diet. No more halal meat, just vegan food please.",
        "I also prefer working from co-working spaces now, not hotel executive lounges.",
        "Nightlife is less important to me now. I prefer early morning activities.",
    ],
    "elena_vasquez": [
        "Update: I am no longer vegetarian. I eat everything now including meat.",
        "I have decided I prefer luxury lodges over eco-lodges. Comfort is important.",
        "I also want guided tours now instead of solo hiking. Safer and more social.",
    ],
    "jordan_taylor": [
        "Our group preferences changed. We actually want a nice hotel now, not the cheapest option.",
        "We are more into cultural experiences than nightlife these days.",
        "Food preferences changed too. We want local cuisine, not fast food.",
    ],
    "alex_brennan": [
        "Big change: I have started eating meat again. Full omnivore now.",
        "I also do not need wifi as my top priority anymore. I am taking a break from remote work.",
        "I now prefer large chain hotels for the loyalty points over boutique places.",
    ],
    "isabelle_dupont": [
        "Update on my dining preferences: I am now fully vegan, not flexitarian.",
        "I also prefer street art and graffiti tours over traditional gallery visits now.",
        "Budget accommodation is fine now. I would rather spend money on art purchases.",
    ],
}


def run_conversation(client, tenant_id, user_id, messages, delay, dry_run=False):
    """Run a multi-turn conversation and return stats."""
    if dry_run:
        for i, msg in enumerate(messages, 1):
            print(f"    {i}. {msg}")
        return {"sent": len(messages), "errors": 0}

    try:
        session_id = client.create_session(tenant_id, user_id)
    except Exception as e:
        log.error("    Failed to create session: %s", e)
        return {"sent": 0, "errors": 1}

    sent = 0
    errors = 0
    for i, msg in enumerate(messages, 1):
        log.info("    [%d/%d] %s", i, len(messages), msg[:80])
        try:
            response = client.send_message(tenant_id, user_id, session_id, msg)
            sent += 1
            assistant_msgs = [
                m for m in response
                if m.get("senderRole") == "Assistant"
                or m.get("sender", "").lower() != "user"
            ]
            if assistant_msgs:
                last = assistant_msgs[-1]
                log.info("    [%s] %s", last.get("sender", "Agent"), last.get("text", "")[:100])
        except httpx.ReadTimeout:
            log.warning("    Timed out -- continuing...")
            errors += 1
        except Exception as e:
            log.error("    Error: %s", e)
            errors += 1
        if i < len(messages):
            time.sleep(delay)

    return {"sent": sent, "errors": errors}


def main():
    parser = argparse.ArgumentParser(
        description="Add preference-conflict conversations to trigger memory supersession."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--tenant", default=DEFAULT_TENANT)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = TravelAppClient(base_url=args.base_url, timeout=args.timeout)

    if not args.dry_run and not client.health_check():
        log.error("Cannot reach Travel API at %s", args.base_url)
        sys.exit(1)

    total_sent = 0
    total_errors = 0

    log.info("=" * 60)
    log.info("PREFERENCE CONFLICT CONVERSATIONS (memory supersession)")
    log.info("=" * 60)
    for user_id, messages in CONFLICT_CONVOS.items():
        log.info("\n  User: %s (%d messages)", user_id, len(messages))
        stats = run_conversation(client, args.tenant, user_id, messages, args.delay, args.dry_run)
        total_sent += stats["sent"]
        total_errors += stats["errors"]

    log.info("\n" + "=" * 60)
    log.info("ENRICHMENT COMPLETE")
    log.info("  Messages sent: %d", total_sent)
    log.info("  Errors: %d", total_errors)
    log.info("=" * 60)

    client.close()


if __name__ == "__main__":
    main()
