# Analytics Initiative — Charter

> Foundational context for the Agent Analytics and Optimization work. ADRs reference this document. Last updated: 2026-07-07.

## Vision

See `vision/agent-analytics-and-optimization-vision.md`. In short: make Microsoft Fabric the analytical and optimization layer for agentic applications, with **Azure Cosmos DB as the operational system of record** and Fabric as the analytical/optimization system of record, forming a continuous learning loop (analyze → recommend → govern → apply → measure).

## Scope of this workshop implementation

- **Pillar coverage:** **all six** analytics pillars from the vision — (1) Agent Performance, (2) Agent Collaboration, (3) Cost Intelligence, (4) Memory Intelligence, (5) Evaluation Intelligence, (6) Workflow Intelligence — built on the existing travel multi-agent app. Memory Intelligence (Pillar 4) is treated as the flagship where we go deepest.
- **Maturity target (confirmed 2026-07-07):**
  - **Levels 1–3 are the buildable core across all pillars:** Visibility (dashboards/semantic model), Recommendations, and Assisted Optimization (propose changes + human approval + apply to the operational store).
  - **Level 4 (Autonomous Optimization): one bounded, honestly-caveated slice** on the lowest-risk domain(s) (e.g., autonomous memory-salience decay / retention pruning; possibly a routing-threshold or model-selection policy) implemented as a scheduled, rule-governed, **reversible + audited** job with a measure→auto-rollback guard. **Honesty caveat:** with synthetic workshop data there is no real outcome signal, so the "validate it improved outcomes" step is **illustrative/demonstrative, not proof**. We demonstrate the autonomy *mechanism and safety loop*, transparently flagged.
  - **Level 5 (Adaptive Agent Systems): conceptual framing only** — an emergent operational maturity from running L4 across many agents over time; narrated/diagrammed, not implemented.
- **Deliverables:**
  1. A full functional implementation in `02_completed/`.
  2. Workshop modules in `01_exercises/` teaching users to build it themselves, with clear learning elements. The all-pillars scope exceeds "one or two modules" — and that is acceptable: **modules may be longer, more numerous, or both** (confirmed 2026-07-07). Coverage should still teach the *pattern* coherently (memory-led), with less central pillars presented more briefly or as reference. Final module count/curation is decided at authoring time (see Open Questions).
  3. This knowledge base (vision, charter, ADRs, deep docs) kept current.

### Lower-risk optimization domains in scope (per the vision's Human-Governed principle)

Memory salience tuning, memory retention/TTL policies, retrieval weighting, routing thresholds, tool/model selection policies, cost optimization — all **human-approved** at Levels 2–3 (and, for the single L4 slice only, auto-applied with guardrails). Higher-risk domains (prompt/workflow/agent-instruction/code changes) remain human-governed and out of scope for autonomous action.

## Data readiness (verified against live Azure Cosmos DB, 2026-07-07)

Inspected the deployed account `cosmos-kfpokdh52vbec` / `TravelAssistant` directly via Entra ID. Findings corrected several earlier assumptions — **this is why we verify against real data**.

**Containers with real, usable data:**
- `Memories` (265): full schema — `memoryType`, `salience`, `ttl`, `lastUsedAt`, `extractedAt`, `facets`, `embedding[1024]`, `supersededBy` when applicable.
- `Sessions` (86): `sessionId`, `userId`, `activeAgent`, `createdAt`, `lastActivityAt`, `status`, `messageCount` → maps to UserSession / WorkflowExecution.
- `Messages` (690): `role`, `content`, `toolCalls`, `embedding[1024]`, `ts`, `keywords`, `superseded` → conversation turns.
- `Trips` (35): nested `days[]` (morning/lunch/afternoon/dinner/accommodation + `placeId`); `Users` (16); `Places` (2937, `embedding[1536]`).

**Containers that do NOT hold the data we assumed:**
- `Debug` (334): the fields exist but the analytical ones are **empty** — verified `total_tokens=0`, `agent_selected="Unknown"`, `previous_agent="Unknown"`, `transfer_success=false` for **all 334** docs; only `model_name` (gpt-4.1-mini) is populated. Root causes (code-verified): (a) tokens read from `response_metadata.token_usage`, but the model runs `streaming=True` (`azure_open_ai.py:41`) so usage isn't surfaced without `stream_usage`/`include_usage` — to confirm by test; (b) `agent_selected`/transition only set when a `transfer_to_` tool call is detected in the passed messages (`travel_agents_api.py:703-708`), which isn't firing. Stored as an awkward EAV `propertyBag` array that needs pivoting for analytics.
- `ApiEvents` (0) and `Summaries` (0): **empty** — `record_api_event` and summary creation aren't producing data in practice.
- `Checkpoints` (19,472): opaque base64 **msgpack** blobs (`type: "msgpack"`) — high volume, low analytical value; **not recommended for mirroring**.

**Implication (corrected):** Pillars 1/2/3 are **NOT** "mirror + model" — they require **fixing instrumentation** (real token capture; real agent/transition capture; add latency) and **regenerating data** before any analytics are possible. This couples directly to the data-generation redesign. Pillar 4 (memory) has real data today.

**Unifying model:** map the app's operational state to the vision's **Open Analytics Schema** (`AgentRun`, `AgentStep`, `AgentTransition`, `ToolInvocation`, `MemoryEvent`, `Checkpoint`, `EvaluationResult`, `TokenUsage`, `UserSession`, `WorkflowExecution`) → mirror the useful subset → Fabric gold per pillar → surfaces. (See ADR-0002.)

## First principles (governing rules for this effort)

1. **Data-grounded, always.** Every assertion — whether made by the human or by an agent — must be grounded in data and **tested and observed to be correct before it is relied upon**. Structural review is not a test. "Should work" is not "works." When something has not been verified, say so explicitly and mark it as an open item to test.
2. **Record every architectural decision as an ADR.** Include context, options considered, the evidence, the decision, and consequences. Keep ADRs current; supersede rather than silently rewrite.
3. **Produce and maintain deep implementation docs** for both humans and agents, so collaborators and their agents can explore and analyze the build and propose intelligent fixes.

## Known constraints (verified)

- The app's Azure Cosmos DB account is provisioned with `disableLocalAuth: true` and (on the analytics branch) provisioned-throughput + continuous backup to support Fabric Mirroring. (See `02_completed/infra/shared/cosmosdb.bicep`.)
- Fabric Mirroring replicates only: **Memories, Users, Trips, Places**.
- Fabric User Data Functions' managed Cosmos connection targets **Cosmos DB *in Fabric***, not an external Azure Cosmos DB account (see ADR-0001).
- Deployed Azure apps cannot connect to Fabric Lakehouse SQL endpoints via managed identity; Azure Cosmos DB is the operational bridge (see ADR-0001).

## Open questions to resolve with evidence (tracked, not yet decided)

- **Data generation for the workshop:** the current live generator costs ~3 hrs / ~10M tokens (per `analytics/README.md`) — not workshop-viable. Need a tested, low-cost data path that also produces the new signals Levels 2–3 require across pillars (memory-retrieval events + outcome linkage, latency, evaluation results, etc.).
- **Open Analytics Schema + mirror-set expansion (candidate ADR-0002):** adopt the vision's 10 core primitives as the canonical instrumentation model emitted to Cosmos, and expand Fabric Mirroring to include `Debug`, `ApiEvents`, `Checkpoints`, `Sessions`, `Messages`. To be decided and validated (RU/cost impact of mirroring more containers to be measured).
- **Per-pillar instrumentation gaps:** latency (Pillar 1), `MemoryEvent` stream + outcome linkage (Pillar 4), `EvaluationResult` persistence to Cosmos (Pillar 5), workflow outcome labeling (Pillar 6). Each to be designed and validated.
- **L4 outcome-validation honesty:** define the proxy/illustrative outcome signal used for the single autonomous slice, and label it clearly as demonstrated-on-synthetic-data.
- **Module curation:** with modules allowed to be longer/more numerous, decide the final module arc at authoring time — how many pillars get full build-along treatment vs. reference.
- **Power BI role:** whether/how to keep Power BI as an optional Level-1 visibility surface once the web-app loop exists.
