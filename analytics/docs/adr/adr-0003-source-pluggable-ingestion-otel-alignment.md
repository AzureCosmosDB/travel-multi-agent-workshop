# ADR-0003: Source-pluggable analytics ingestion — OpenTelemetry GenAI semconv as the interop standard; the Open Analytics Schema as a first-party normalization layer

- **Status:** Proposed
- **Date:** 2026-07-07
- **Deciders:** Mark Brown (@markjbrown), with agent analysis
- **Related:** `../vision/agent-analytics-and-optimization-vision.md`, `../charter.md`, ADR-0001, ADR-0002

## Context

ADR-0002 chose the vision's **Open Analytics Schema (OAS)** as the canonical analytical model and rejected "external telemetry (LangSmith / OpenTelemetry) as the *primary* analytics source" (Option C), keeping Azure Cosmos DB operational state as the system of record (ADR-0001). Two follow-up questions were raised that this ADR resolves:

1. Does not sourcing from LangSmith/OTel make the build harder, and would other agent frameworks (e.g., Microsoft Agent Framework) adopt LangSmith or OpenTelemetry?
2. Can we later abstract the providers and let the OAS sit above them as a generic analytics layer over multiple agent/observability frameworks?

A prerequisite fact was checked first: **is "Open Analytics Schema" an external standard?** It is not — see Evidence. It is coined in this repo's vision doc. That means the schema is *ours to define*, and the highest-leverage design is to define it as a thin projection over the **real** external standards rather than an invented vocabulary.

## Decision drivers

- Keep the vision's framework-agnostic promise real: "adopt new frameworks without changing analytics/optimization" (vision.md:191–206).
- Preserve the operational-state-first differentiator (Cosmos persists memory lifecycle, checkpoints, transitions, outcomes that ephemeral traces do not).
- Avoid inventing a vocabulary that diverges from where the industry is converging.
- Low cost now, optionality later: make future OTel/OpenInference ingestion a mapping exercise, not a re-model.

## Options considered

### Option A — Leave OAS as a free-standing bespoke vocabulary; integrate other sources ad hoc later
**Rejected.** Re-invents concepts the ecosystem already standardizes (tokens, tool calls, agent/eval spans); every future source becomes a bespoke integration; diverges from OTel/OpenInference naming, raising long-term mapping cost.

### Option B — Define the OAS as a first-party normalization layer explicitly aligned to OpenTelemetry GenAI semantic conventions (`gen_ai.*`) and OpenInference; make ingestion source-pluggable *(chosen)*
The OAS stays first-party (it must, to carry operational-state primitives OTel lacks), but each OAS field is defined with its `gen_ai.*` counterpart where one exists. Ingestion is an adapter seam: **source → adapter → OAS → gold → surfaces**. Sources: (1) Cosmos operational state [today], (2) OTel GenAI spans, (3) OpenInference, (4) framework-native adapters [later].

### Option C — Switch the primary source to OTel/LangSmith now
**Rejected for now** (restates ADR-0002 Option C). OTel GenAI semconv is still **Development/experimental** (Evidence); traces don't carry memory salience/TTL/supersede, checkpoints, or routing outcomes; and standing up a collector + backend bloats a teaching repo. Revisit if/when the semconv stabilizes and a workshop-appropriate backend exists.

## Evidence

### "Open Analytics Schema" is first-party, not an external standard
- Defined only in `../vision/agent-analytics-and-optimization-vision.md:275–292` ("an open analytical schema representing the core execution primitives common across agent frameworks") with 10 primitives.
- Web check (2026-07-07): no established open standard by that exact name. The real neighbours are **OpenInference** (Arize; open schema for LLM/agent spans), **OpenTelemetry GenAI semconv** (`gen_ai.*`), and **OpenLLMetry** (Traceloop). ("Open Agent Spec" is agent *definition*, a different concern.)

### Framework adoption (verified 2026-07-07)
- **LangSmith** is a LangChain-oriented vendor backend; it now supports **OTLP** import/export but is not a neutral cross-framework standard. In this app it is already wired opt-in via `@langsmith.traceable` (`02_completed/python/src/app/travel_agents.py:24`, `services/azure_cosmos_db.py:11`, `mcp_server/mcp_http_server.py:6`) and `LANGCHAIN_*` env.
- **OpenTelemetry GenAI semconv** is the emerging cross-framework standard. **Microsoft Agent Framework emits `gen_ai.*` spans natively** — verified against its Learn observability doc (updated 2026-06-26): it "emits traces, logs, and metrics according to the OpenTelemetry GenAI Semantic Conventions," enabled via `.UseOpenTelemetry(sourceName)` (chat client) / `.WithOpenTelemetry(sourceName)` (agent), default source `Experimental.Microsoft.Agents.AI`. Semantic Kernel shares this lineage; LangChain/CrewAI/AutoGen converge on it; OpenAI Agents SDK has OTel exporters. *(Caution: a web-search summary returned invented attribute names like `genai.agent.tool_calls`/`genai.llm.model_id`; these are NOT real `gen_ai.*` names and were discarded in favor of the authoritative registry.)*
- **Version pinned:** the dedicated `open-telemetry/semantic-conventions-genai` repo has **no release tags** (GitHub tags API returned `[]`, 2026-07-07); this ADR maps against `main` commit **`c321d7eb4443ae1d1d88c2e24eda849f62049008`** (2026-07-04). Track drift against that SHA.
- **Status caveat:** every `gen_ai.*` attribute in the authoritative registry is badged **Development** (experimental), i.e. widely used but not frozen — so we *align to* it, we don't *depend on* it yet. Source: OpenTelemetry GenAI semantic-conventions repo (registry + spans docs).

### OAS ↔ OTel GenAI semconv mapping (authoritative `gen_ai.*` names)
Verified against the OTel GenAI registry (`docs/registry/attributes/gen-ai.md`) and spans doc.

| OAS primitive | OTel GenAI coverage | Key `gen_ai.*` attributes | Notes |
|---|---|---|---|
| **TokenUsage** | ✅ Direct 1:1 | `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_creation.input_tokens`, `gen_ai.usage.reasoning.output_tokens` | Our LangChain `usage_metadata` maps directly (see verification doc). |
| **AgentStep** (inference) | ✅ Strong | `gen_ai.operation.name`=`chat`, `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.response.finish_reasons`, `gen_ai.response.id`, `gen_ai.request.stream`, `gen_ai.provider.name` | Latency: `gen_ai.response.time_to_first_chunk` (streaming). |
| **AgentRun** (invocation) | ✅ Good | `gen_ai.operation.name`=`invoke_agent`, `gen_ai.agent.name`, `gen_ai.agent.id`, `gen_ai.agent.version`, `gen_ai.conversation.id` | |
| **ToolInvocation** | ✅ Strong | `gen_ai.operation.name`=`execute_tool`, `gen_ai.tool.name`, `gen_ai.tool.type`, `gen_ai.tool.description`, `gen_ai.tool.call.id`, `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result` | |
| **MemoryEvent** | ⚠️ Partial | `gen_ai.memory.query.text`, `gen_ai.memory.record.count`, `gen_ai.memory.record.id`, `gen_ai.memory.records`, `gen_ai.memory.store.id` | OTel covers store/retrieve; **salience / TTL / supersede lifecycle is first-party** (our differentiator). |
| **EvaluationResult** | ✅ Good | `gen_ai.evaluation.name`, `gen_ai.evaluation.score.value`, `gen_ai.evaluation.score.label`, `gen_ai.evaluation.explanation` | |
| **UserSession** | ⚠️ Join-key only | `gen_ai.conversation.id` | Session as a business entity is broader than a conversation id. |
| **AgentTransition** | ❌ No native primitive | (model as attributes/event on an agent span) | Our `transfer_to_*` routing/handoff; **first-party differentiator**. |
| **Checkpoint** | ❌ No native primitive | (`gen_ai.conversation.compacted` is adjacent, not equivalent) | Operational state, not telemetry; **first-party differentiator**. |
| **WorkflowExecution** | ❌ No stable primitive | (framework-specific) | Session-level outcome/labeling; **first-party differentiator**. |

**Reading:** OTel cleanly standardizes ~6 of 10 primitives; the remaining 3–4 (AgentTransition, Checkpoint, WorkflowExecution, plus memory *lifecycle* depth) are exactly the operational-state concepts that justify Cosmos-as-primary — the parts an ephemeral trace standard does not carry. So sourcing from Cosmos does **not** make the core job harder; the standardized parts we adopt for free via naming, and the non-standardized parts are our value-add.

### OpenInference divergence (verified 2026-07-07, `Arize-ai/openinference` spec)
OpenInference is a **second** open standard and its names **differ from OTel** — the adapter must translate, not assume identity. Key deltas (verified against `spec/semantic_conventions.md`):
- **Span typing:** a required `openinference.span.kind` (`LLM`/`TOOL`/`AGENT`/`RETRIEVER`/`EVALUATOR`/…) rather than OTel's `gen_ai.operation.name`.
- **Tokens:** `llm.token_count.prompt` / `llm.token_count.completion` / `llm.token_count.total`, cached via `llm.token_count.prompt_details.cache_read` — vs OTel's `gen_ai.usage.input_tokens`/`output_tokens`/`cache_read.input_tokens`. (Note prompt/completion vs input/output naming.)
- **Provider/model:** `llm.provider`, `llm.model_name`, `llm.finish_reason` — vs `gen_ai.provider.name`, `gen_ai.response.model`, `gen_ai.response.finish_reasons`.
- **Bonus OpenInference has that OTel lacks:** explicit **cost** fields (`llm.cost.prompt`/`completion`/`total` in USD) — worth adopting for Pillar 3 cost analytics.

**Implication:** OAS field definitions should carry mappings to **both** vocabularies (OTel `gen_ai.*` and OpenInference `llm.*`), since the two "open" standards disagree on token/provider naming.

## Decision

1. **The Open Analytics Schema remains first-party** (it must, to carry operational-state primitives OTel omits), and is **defined as a normalization layer explicitly aligned to OpenTelemetry GenAI semantic conventions and OpenInference.** Each OAS field records its `gen_ai.*` counterpart where one exists (start with the table above).
2. **Adopt `gen_ai.*`-aligned field names now** for the new/fixed telemetry emitted per ADR-0002 — highest value for `TokenUsage`, `ToolInvocation`, `MemoryEvent`, `EvaluationResult`, `AgentRun`/`AgentStep`. Near-zero extra cost; makes any future OTel source a 1:1 map.
3. **Ingestion is source-pluggable via an adapter seam:** `source → adapter → OAS → gold → surfaces`. Cosmos operational state is source #1 today; OTel GenAI spans and OpenInference are future sources that require an adapter, not a re-model.
4. **Do not adopt OTel/LangSmith as the primary source yet** (per ADR-0002 Option C); revisit when the GenAI semconv reaches Stable and a workshop-appropriate backend is justified. LangSmith stays as optional opt-in developer tracing only.

## Consequences

- **Positive:** future-proofs the schema against the converging standard at near-zero cost; keeps the operational-state differentiator; turns "add a framework/source" into an adapter task; honestly scopes what OTel does and doesn't give us.
- **Negative / costs:** we track an **experimental** spec (names may shift before 1.0) — mitigated by keeping OTel names as *aliases/annotations* on first-party fields, not as the storage contract; small upfront effort to annotate field mappings.
- **Risks:** semconv churn; over-fitting OAS to today's `gen_ai.*` shapes; adapter drift if multiple sources disagree on a primitive's semantics.

## Open items to verify

- ~~**Confirm Microsoft Agent Framework's exact `gen_ai.*` emission**~~ **✅ Done (2026-07-07):** verified against the Learn observability doc — emits OTel GenAI semconv via `.UseOpenTelemetry`/`.WithOpenTelemetry`, source `Experimental.Microsoft.Agents.AI`. When we build that adapter, confirm the exact span/attribute *coverage* against a live capture (doc asserts conformance; capture confirms completeness).
- ~~**Confirm OpenInference span/attribute names**~~ **✅ Done (2026-07-07):** verified; names diverge from OTel (see "OpenInference divergence"). Adapter must translate token/provider names; OpenInference adds `llm.cost.*`.
- ~~**Pin a semconv version**~~ **✅ Done:** no release tags exist; pinned to `semantic-conventions-genai` `main` @ `c321d7eb` (2026-07-04). Re-check on drift.
- **Remaining:** capture a **live** OTel/OpenInference span from each target framework before building its adapter, to confirm attribute completeness (doc conformance ≠ observed emission).

## References

- OpenTelemetry GenAI semantic conventions — `https://github.com/open-telemetry/semantic-conventions-genai` @ `main` `c321d7eb4443ae1d1d88c2e24eda849f62049008` (2026-07-04); files `docs/registry/attributes/gen-ai.md`, `docs/gen-ai/gen-ai-spans.md`. Status: Development/experimental. No release tags as of 2026-07-07.
- Microsoft Agent Framework — Observability: `https://learn.microsoft.com/en-us/agent-framework/agents/observability` (updated 2026-06-26).
- OpenInference (Arize) — `https://github.com/Arize-ai/openinference` (`spec/semantic_conventions.md`).
- Vision: `../vision/agent-analytics-and-optimization-vision.md:191–206, 275–292, 351`.
- Token-capture verification: `../verification/2026-07-07-token-capture.md`.
