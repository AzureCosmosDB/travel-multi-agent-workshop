"""
Marvel user data seeder.

The four users that ship with the app (tenant ``marvel``: tony, steve, bruce,
peter) are the only ones that appear on the frontend login screen, but the base
seed gives them no trips or memories. This script drives a few in-character
conversations through the *running* Travel API for each of them so the login
users have realistic memories (preferences) and at least one confirmed trip.

Prereqs: the MCP server (:8080) and Travel API (:8000) must be running against
the target Cosmos database.

Usage:
    python analytics/scripts/marvel_seed.py                      # default http://localhost:8000
    python analytics/scripts/marvel_seed.py --base-url http://...:8000
    python analytics/scripts/marvel_seed.py --dry-run            # print plan only
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass

import httpx


@dataclass
class Conversation:
    """A multi-turn conversation that a simulated user will have."""
    title: str
    messages: list[str]  # user messages to send in order


class TravelAppClient:
    """Minimal HTTP client that talks to the running Travel Multi-Agent API."""

    def __init__(self, base_url: str, timeout: float = 180):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout)

    def health_check(self) -> bool:
        try:
            r = self.client.get(f"{self.base_url}/health")
            return r.status_code == 200
        except httpx.ConnectError:
            return False

    def create_session(self, tenant_id: str, user_id: str) -> str:
        url = f"{self.base_url}/tenant/{tenant_id}/user/{user_id}/sessions"
        r = self.client.post(url, params={"activeAgent": "orchestrator"})
        r.raise_for_status()
        data = r.json()
        return data.get("sessionId") or data.get("id")

    def send_message(self, tenant_id: str, user_id: str, session_id: str, message: str) -> list[dict]:
        url = (
            f"{self.base_url}/tenant/{tenant_id}/user/{user_id}"
            f"/sessions/{session_id}/completion"
        )
        # The API expects a raw JSON string, not an object
        r = self.client.post(
            url,
            content=json.dumps(message),
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return r.json()

    def get_memories(self, tenant_id: str, user_id: str) -> list[dict]:
        url = f"{self.base_url}/tenant/{tenant_id}/user/{user_id}/memories"
        r = self.client.get(url)
        r.raise_for_status()
        return r.json()

    def get_trips(self, tenant_id: str, user_id: str) -> list[dict]:
        url = f"{self.base_url}/tenant/{tenant_id}/user/{user_id}/trips"
        r = self.client.get(url)
        r.raise_for_status()
        return r.json()

    def close(self):
        self.client.close()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("marvel-seed")

TENANT = "marvel"

# Each entry: user_id -> list[Conversation]. The user docs already exist (seeded
# from users.json), so we only create sessions and send messages. Conversations
# state durable preferences (-> memories) and end by asking for an itinerary
# (-> a trip).
MARVEL_CONVERSATIONS: dict[str, list[Conversation]] = {
    # Tony Stark — luxury, tech-forward, moves fast.
    "tony": [
        Conversation(
            title="Tokyo tech-and-luxury weekend",
            messages=[
                "I'm heading to Tokyo for a few days. I only stay in 5-star hotels with great design and a good gym.",
                "Show me luxury hotels in Tokyo — I prefer ultra-modern properties with skyline views.",
                "For food I like high-end sushi and anything innovative. Money is not a concern.",
                "I always want the fastest, most efficient schedule — no wasted time.",
                "Recommend some cutting-edge tech and design spots — I love robotics and gadgets.",
                "Great. Build me a 3-day Tokyo itinerary for March 12-14, 2026.",
            ],
        ),
    ],
    # Steve Rogers — classic, history, museums, disciplined.
    "steve": [
        Conversation(
            title="London history trip",
            messages=[
                "I'd like to visit London. I appreciate historic hotels with character over flashy modern ones.",
                "Find me a classic, centrally located hotel near the museums.",
                "I prefer simple, hearty food — nothing too fancy. Good classic restaurants please.",
                "I'm an early riser and like to start sightseeing first thing in the morning.",
                "I'm really interested in history and museums — World War II sites especially.",
                "Please create a 4-day London itinerary for April 20-23, 2026.",
            ],
        ),
    ],
    # Bruce Banner — quiet, science, calm, avoids crowds.
    "bruce": [
        Conversation(
            title="Kyoto quiet retreat",
            messages=[
                "I want a calm, low-key trip to Kyoto. I strongly prefer quiet places away from crowds.",
                "Find me a peaceful, traditional ryokan or a quiet boutique hotel.",
                "I'm vegetarian, so I need good vegetarian restaurant options.",
                "I like temples, gardens, and anything contemplative — I avoid busy tourist spots.",
                "A science or botanical museum would be great if there is one.",
                "Please build a 3-day Kyoto itinerary for May 5-7, 2026.",
            ],
        ),
    ],
    # Peter Parker — young, budget-conscious, energetic, student.
    "peter": [
        Conversation(
            title="Barcelona on a student budget",
            messages=[
                "Hey! I'm a student planning a budget trip to Barcelona.",
                "Find me cheap but fun hostels or budget hotels, ideally with a social vibe.",
                "I love cheap eats and street food — tapas on a budget, that kind of thing.",
                "I'm always up for walking everywhere to save money, and I love photography.",
                "Show me fun, affordable activities — beaches, markets, cool architecture.",
                "Awesome, make me a 4-day Barcelona itinerary for June 8-11, 2026.",
            ],
        ),
    ],
}


def run(base_url: str, dry_run: bool, delay: float = 2.0) -> int:
    client = TravelAppClient(base_url)
    if not client.health_check():
        log.error("API not reachable at %s — start the MCP server and Travel API first.", base_url)
        return 1

    for user_id, conversations in MARVEL_CONVERSATIONS.items():
        log.info("=== %s (tenant=%s) ===", user_id, TENANT)
        for convo in conversations:
            log.info("  Conversation: %s (%d messages)", convo.title, len(convo.messages))
            if dry_run:
                for m in convo.messages:
                    log.info("    -> %s", m)
                continue
            session_id = client.create_session(TENANT, user_id)
            log.info("  Session: %s", session_id)
            for i, message in enumerate(convo.messages, 1):
                try:
                    client.send_message(TENANT, user_id, session_id, message)
                    log.info("    [%d/%d] sent", i, len(convo.messages))
                except Exception as e:  # noqa: BLE001
                    log.error("    [%d/%d] failed: %s", i, len(convo.messages), e)
                time.sleep(delay)
        if not dry_run:
            try:
                memories = client.get_memories(TENANT, user_id)
                trips = client.get_trips(TENANT, user_id)
                log.info("  >> %s now has %d memories and %d trips.", user_id, len(memories), len(trips))
            except Exception as e:  # noqa: BLE001
                log.warning("  Could not fetch summary for %s: %s", user_id, e)
    log.info("Marvel seed complete.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed trips + memories for the 4 Marvel login users.")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between messages")
    args = ap.parse_args()
    sys.exit(run(args.base_url, args.dry_run, args.delay))


if __name__ == "__main__":
    main()
