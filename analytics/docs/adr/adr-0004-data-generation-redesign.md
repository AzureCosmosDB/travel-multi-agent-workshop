# ADR-0004: Data-generation redesign — make analytics data cheap, reproducible, and real-enough

- **Status:** Proposed
- **Date:** 2026-07-07
- **Deciders:** Mark Brown (@markjbrown), with agent analysis
- **Related:** `../vision/agent-analytics-and-optimization-vision.md`, `../charter.md`, ADR-0002 (instrumentation), ADR-0003 (schema/ingestion)

## Context

The analytics pillars need populated, believable data: token usage, agent transitions, tool invocations, memory lifecycle events, evaluations, and session outcomes. The current generator produces genuinely *real* data by driving the live app, but it is **not workshop-viable** on time/cost, and — until ADR-0002's instrumentation fix lands — the analytics fields it produces are **empty** anyway (verified).

This ADR decides how we generate/seed analytics data for the workshop and the reference solution.

## Decision drivers

- **Workshop-viable:** a learner should get a populated dataset in **minutes**, not hours, ideally at **near-zero token cost**.
- **Reproducible/deterministic:** module steps must produce the same data every run so instructions and screenshots stay valid.
- **Real-enough:** must preserve the semantics the pillars teach — real memory supersession, real routing/transitions, realistic token/latency distributions — not obviously-fake noise.
- **Honest:** any synthetic data must be clearly labeled as synthetic (per our verification-discipline principle); it must not masquerade as observed production data.
- **Minimal new infra**, and must **couple to ADR-0002** (capture the primitives correctly) and **ADR-0003** (emit OTel-aligned field names).

## Evidence (current generator, code-verified 2026-07-07)

- `analytics/data_generator.py` (1006 lines) drives the **live app over HTTP**: per persona → `create_user` → `create_session` → `send_message` = `POST /tenant/{t}/user/{u}/sessions/{s}/completion`, which runs the **full LangGraph graph** against **real Azure OpenAI**. `analytics/data_enricher.py` adds preference-conflict conversations to trigger memory supersession.
- **Measured workload** (`--dry-run`, stubbed import): **12 personas, 32 conversations, 292 generator messages + 19 enricher messages = 311 user messages.** Conversations are 2–10 messages (median 10).
- **Cost multiplier:** each message = one full graph execution = *several* LLM calls (orchestrator routing + specialist + tool calls + memory extraction + periodic summarization). Defaults add `DEFAULT_DELAY=3s` between messages and `DEFAULT_TIMEOUT=300s`/request; sequential by default (`--parallel 3-4` cuts wall-clock). Prior session note observed **~3 hrs / ~10M tokens** for a full run (not re-measured here; consistent with 311 messages × several calls).
- **Blocking dependency (verified in ADR-0002):** the deployed `analytics_demo` data (Memories 265 / Sessions 86 / Messages 690) came from this generator, yet `Debug` analytical fields are **empty** (tokens=0, agent="Unknown", transfer_success=false for 334/334). **Re-running the current code would reproduce empty analytics** until the ADR-0002 instrumentation fix (`usage_metadata` reader + reliable transition/latency capture) lands.

## Options considered

### Option A — Optimize the live-driven generator in place
Keep driving the real app, but cut cost: remove the 3s delay, raise `--parallel`, cap graph work per message, use a cheaper generation deployment / enable prompt caching, and ship a small default persona subset. **Pros:** 100% real data; smallest code change. **Cons:** still needs the running app + Azure OpenAI + real tokens; runtime measured in many minutes even optimized; non-deterministic; still blocked on ADR-0002 to capture analytics.

### Option B — Two-tier: small real seed + synthetic bulk telemetry
Run the live app for a *curated* subset (genuine memory supersession, transitions, trips), then **synthesize the high-volume analytics primitives** (`TokenUsage`/`AgentStep`/`AgentTransition`/`ToolInvocation` rows) directly into the telemetry containers with realistic distributions **and no LLM calls**. **Pros:** cheap, scalable, fast. **Cons:** synthetic rows must be labeled and their distributions justified; two code paths to maintain.

### Option C — Record-and-replay
Capture one real run's requests/responses/telemetry, then replay/clone with parameterized variation to multiply volume without re-calling the model. **Pros:** real-derived, reproducible. **Cons:** need a replay harness; capture fidelity work.

### Option D — Committed, versioned, real-derived fixture loaded by the seed script *(candidate default)*
Capture **one** good real run (after the ADR-0002 fix) into a **versioned dataset artifact** in the repo; the seed script (`python/data/seed_data.py` pattern) loads it straight into Cosmos. The workshop does **not** regenerate by default. **Pros:** near-zero cost, seconds to load, fully deterministic, real-derived, offline-friendly. **Cons:** static (no variety unless refreshed); repo-size cost; must refresh when schema changes.

## Decision (proposed — pending review)

**Recommended: D as the default + A as an optional "generate your own" advanced path, both gated on the ADR-0002 instrumentation fix; B/C as future scale-out.**

1. **Land ADR-0002's instrumentation fix first** (hard prerequisite — otherwise every path yields empty analytics).
2. **Default workshop path = Option D:** a committed, versioned, **real-derived** fixture (captured from one post-fix live run), loaded by the seed script in seconds at zero token cost — deterministic for module instructions.
3. **Advanced/optional path = Option A:** an optimized live generator (no delay, parallel, cheaper generation model, smaller default persona set) for learners who want to watch real data being produced and captured correctly.
4. **Emit OTel-aligned fields** (ADR-0003) from whichever path, so the captured fixture already speaks `gen_ai.*`.
5. **Label provenance explicitly:** the fixture is real-derived-but-static; if any values are backfilled/synthesized (Option B later), tag them as synthetic in the data.

*This is a design decision and is left **Proposed** for your approval before implementation.*

## Consequences

- **Positive:** workshop runs in minutes at ~zero cost; deterministic teaching; keeps a real-data story; aligns emitted fields to the standard from day one.
- **Negative / costs:** capturing the fixture requires one real (post-fix) run; a versioned dataset adds repo size and a refresh chore on schema changes; maintaining two paths (fixture + optional live).
- **Risks:** static fixture can drift from the schema; synthetic backfill (if added) could mislead if not clearly labeled; Option A's realism still depends on Azure OpenAI TPM availability.

## Open items to verify

- **Re-measure the live run cost/time** on current infra *after* the ADR-0002 fix (replace the ~3 hrs/~10M-token prior estimate with a measured number, incl. `--parallel` speedup).
- **Size the fixture artifact** (row counts × containers) and decide storage format/location (JSON under `analytics/` vs. a released asset) given repo-size limits.
- **Define credible distributions** for any synthesized primitives (Option B) and how to validate them against the real seed.
- **Confirm the seed path**: reuse `python/data/seed_data.py` conventions and the hierarchical partition key `[tenant_id, user_id, session_id]`.

## References

- Current generator: `analytics/data_generator.py`, `analytics/data_enricher.py`; workshop docs `analytics/README.md`.
- Instrumentation dependency: ADR-0002 + `../verification/2026-07-07-token-capture.md`.
- Schema/field-naming: ADR-0003.
