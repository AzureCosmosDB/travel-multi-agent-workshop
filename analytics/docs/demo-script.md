# Multi-Agent Travel Demo — Presenter Runbook

This runbook follows the supplied Word source in its exact five-demo order while using the current
application and controlled-demo runtime contract. It intentionally contains no environment
addresses. A single presenter can run the complete sequence.

## Five-demo sequence

1. Frontend application
2. Cosmos, mirroring, and SQL endpoint
3. Fabric notebook
4. User Data Function
5. Power BI and web analytics portal

Use the conceptual talk track below, but treat the current repository behavior as operational
truth. Do not improvise reset, policy, traffic, or recompute operations.

## Presentation modes

### Portal Live mode

This is the only mode that performs controlled mutation during the presentation. Run the serial,
fail-closed sequence in [Controlled preparation](#controlled-preparation), then use the web
analytics portal to Apply, Generate traffic, and Recompute. Power BI is refreshed only after
Cosmos and the mirror converge.

### Prepared Fabric / Power BI mode

Prepare and validate the complete snapshot off-stage. During the presentation, do not reset,
apply/revert, generate traffic, freshen timestamps, or run the full notebook unless that exact
operation was separately rehearsed. Show the prepared Cosmos rows, mirror, SQL endpoint,
completed notebook output, User Data Function code, Power BI report, and portal snapshot.

## Browser setup

Use separate browser instances or clearly separated browser windows so authentication and
navigation state do not collide.

| Browser instance | Tab | Required location before presenting |
|---|---|---|
| Travel app | Explore | Seeded user signed in; Profile and Memories reachable |
| Travel app | Trips | Planned Barcelona trip visible |
| Azure portal | Cosmos Data Explorer | `TravelAssistant` database |
| Fabric | Mirrored database | Mirrored `TravelAssistant` database and replication status |
| Fabric | SQL analytics endpoint | `TravelAssistant` tables, especially `OptimizationTurns` and `OptimizationInsights` |
| Fabric | Notebook | Completed `ConversionFunnelReverseETL` notebook at the top |
| Fabric | User Data Function | `optimization-apply-loop`, with apply, revert, and internal status-write functions visible |
| Fabric | Power BI | Portfolio Overview; Optimizations ready |
| Hosted app | Web analytics portal | Overview; Optimizations, Model Selection, Memory, Agents, Business, and Governance reachable |

## Demo setup — complete before presenting

Complete every step in this section before starting **Demo 1**. The audience-facing demo begins
only after Analytics has its second 200-turn burst, recompute and mirroring have completed, Power
BI has been refreshed, and all readiness checks pass.

## Recommended pre-demo state

The supplied demo guide moves from **Marvel** to **Analytics** to show the before and after of
model-selection optimization. Prepare the complete comparison before the audience arrives:

- **Marvel = Before:** model-selection is not applied, all 200 controlled turns use the premium
  model, and no measured result exists.
- **Analytics = After:** reset first creates the same 200-turn premium baseline, then
  model-selection is applied and the traffic generator adds a second 200-turn optimized burst.
  Analytics is ready with 400 controlled turns and a measured result.

Do not apply model-selection to Marvel while preparing this demo. Marvel is the unchanged
comparison dataset.

### Exact preparation sequence

Perform these steps in the **web analytics portal**. Wait for each operation to finish and refresh
successfully before starting the next one.

1. Open the portal and confirm **Tenant = Analytics**.
2. Open **Demo tools** using the gear button.
3. Select **Reset to baseline**, read the confirmation, and confirm the reset.
4. Wait for the success message. If reset reports an error, stop; do not generate traffic or
   recompute.
5. Select **Recompute insights**. This creates the baseline analytical snapshot for both controlled
   tenants.
6. Verify the baseline:
   - Marvel: 200 premium turns, model-selection not applied, no measured result.
   - Analytics: 200 premium turns, model-selection not applied, no measured result.
7. With **Tenant = Analytics**, open **Optimizations**, select the capability-tiered
   model-selection recommendation, and select **Apply**.
8. Verify the Analytics policy state is **Active**, **Applied**, or **Awaiting Traffic**. Marvel
   must remain **Not Applied**.
9. Open **Demo tools** and select **Generate traffic** exactly once. This control always generates
   the deterministic Analytics after-burst; it does not generate Marvel traffic.
10. Wait for the success message reporting **200 turns** and a tiered model mix.
11. Open **Demo tools** and select **Recompute insights** exactly once.
12. Wait for recompute to finish, then allow the Fabric mirror to converge.
13. Refresh Power BI and verify the values in
    [Pre-demo readiness checks](#pre-demo-readiness-checks).

Do not select **Freshen turn times** as part of this sequence. It is not required for the
controlled before/after comparison.

### Timing guidance

The traffic generator creates 200 logical Analytics turns across six controlled containers, which
is approximately 1,200 document upserts. The operation does not have a fixed duration guarantee;
Cosmos throughput, retry backoff, recompute time, and Fabric mirror convergence can all vary.

Do not put this wait in the live presentation. Reserve at least five minutes during setup for
Generate traffic, Recompute insights, mirror convergence, Power BI refresh, and final validation.
The demo is ready only when the readiness checks pass, regardless of elapsed time.

### What Reset to baseline changes

Reset creates a backup before mutation, reverts the tenant-qualified model-selection policies for
both Marvel and Analytics, removes only controlled-fixture rows, and reseeds the canonical
two-tenant baseline.

The controlled fixture spans these containers:

- `OptimizationTurns`
- `Debug`
- `NodeExecutions`
- `Sessions`
- `Messages`
- `Trips`

Reset also clears the controlled derived rows in:

- `OptimizationInsights`
- `OptimizationGovernance`

Only rows carrying the controlled fixture identity are replaced. Normal user/profile data,
memories, and operational rows outside the controlled fixture remain untouched. In particular,
operational trips are protected; reset does not broadly delete the tenant's trips. If a protected
row collides with a controlled fixture ID, reset fails instead of overwriting it.

After reset:

- both tenants contain the same canonical 200-turn premium-model baseline;
- both model-selection policies are reverted;
- controlled derived insight/governance rows are empty until **Recompute insights** runs;
- the backup can restore the pre-reset fixture and policy state if a later reset step fails.

### What Generate traffic changes

During setup, the portal's controlled **Generate traffic** action requires the Analytics
model-selection policy to be active. It replaces only the named Analytics after-burst namespace
across the same six controlled cohort containers.

One successful run adds exactly 200 Analytics turns over 20 minutes:

- 70 premium (`gpt-5.1`)
- 110 mini (`gpt-5-mini`)
- 20 nano (`gpt-5-nano`)

The burst is deterministic and safe to retry with the same parameters: an existing matching burst
is replaced, not appended repeatedly. Conflicting burst parameters fail closed. Marvel is not
changed.

### What Recompute insights changes

**Recompute insights** rebuilds the controlled `OptimizationInsights` snapshot after the source
rows are correct. It processes the controlled state serially and refreshes the Business, Memory,
Governance, optimization, policy, and measured-result rows used by the portal and Power BI.

Recompute does not generate traffic and does not apply a policy. Always establish the source state
first, then recompute, then wait for the mirror, and only then refresh Power BI.

### Dirty-state preflight

1. Confirm the intended Azure identity, subscription, resource group, Container Apps revisions,
   Cosmos account/database, Fabric workspace, mirror, notebook, User Data Function, semantic model,
   and report.
2. Stop any practice traffic generator or notebook refresh.
3. Capture a durable backup of every fixture-owned Marvel and Analytics row that controlled reset
   may mutate, plus the current policy documents and deployed Fabric/Power BI definitions.
4. Record the active Container Apps revisions, images, and traffic weights.
5. Verify the backup is readable before mutation. If identity, inventory, or backup verification
   is incomplete, stop.

### Deployment and seed boundary

`azd up` may seed an empty environment or idempotently ensure initial seed records during
deployment. It never invokes the controlled reset, never generates the controlled traffic burst,
and never silently restages an existing demonstration. Reset is a deliberate operator action in
the web analytics portal.

### Serial baseline preparation

1. In the web analytics portal, run **Reset to baseline** for the approved controlled fixture.
2. Validate the direct Cosmos baseline before recomputing derived rows:
   - Marvel: 200 all-premium turns, no applied model-selection policy, Before state.
   - Analytics: 200 all-premium turns, no applied model-selection policy, Before state.
   - Each cohort has 20 populated minute buckets and funnel `192 → 184 → 92 → 56`.
   - Conversion is `29.2%`; `city_friction` is the largest cause.
   - Operational user trips outside fixture ownership remain present.
3. Run **Recompute insights** only after the direct source checks pass.
4. Wait for mirror convergence. Verify row counts and the expected baseline through the SQL
   analytics endpoint.
5. Refresh Power BI and verify both tenant views before presenting.

Run reset, validation, recompute, mirror verification, and report refresh **serially**. Do not
start a later step while an earlier one is still converging.

### Optional rehearsal of the controlled transition

Use this sequence only while rehearsing or rebuilding the prepared state before the presentation.
Do not run it during the audience-facing demo. The Power BI presentation uses the already prepared
state from [Exact preparation sequence](#exact-preparation-sequence).

1. Select the Analytics demonstration dataset and Apply the model-selection recommendation.
2. Verify the state is **Policy Active · Awaiting Traffic · Before**.
3. Run **Generate traffic** once. The controlled burst adds 200 Analytics turns across 20 minutes:
   20 nano, 110 mini, and 70 premium.
4. Validate the direct Cosmos rows and model mix.
5. Run **Recompute insights** once.
6. Wait for mirror convergence and verify through the SQL analytics endpoint.
7. Refresh Power BI and compare:
   - Marvel remains **Not Applied · Before**.
   - Analytics is **Applied · After**, with 400 turns total and model mix 270 premium, 110 mini,
     and 20 nano.
8. Treat the controlled Analytics saving as **Measured**. Recommendation-card and volume values
   remain **Projected** or **Estimated**.

Revert changes future behavior; it does not erase already captured After traffic.

### Pre-demo readiness checks

Do not begin the presentation until all of these checks pass:

| Check | Marvel Before | Analytics After |
|---|---:|---:|
| Controlled turns | 200 | 400 |
| Premium turns | 200 | 270 |
| Mini turns | 0 | 110 |
| Nano turns | 0 | 20 |
| Active model-selection policies | 0 | 1 |
| Measured saving | Blank / Not measured yet | 2.8005 |
| Estimated saving | 13.17991 | 18.176147 |
| Ranked opportunity rows | Exactly 1 | Exactly 1 |
| Ranked opportunity state | Not Applied | Active / Applied |

Also verify:

- the Marvel and Analytics tenant slicers each remove the other tenant's ranked row;
- the recommendation cards remain below the ranked opportunity feed as a separate list;
- the planned Barcelona trip and other protected operational trips still exist;
- `OptimizationInsights` has refreshed rows and the mirror is no longer catching up;
- no lifecycle operation is still showing a loading or error state.

### Fail-closed and rollback

- Missing, incomplete, duplicate, conflicting, malformed-token, unknown-deployment, or
  wrong-model-mix rows are failures, not acceptable Before/After states.
- If a mutation or deployment step fails, stop the sequence. Do not continue to recompute or
  refresh presentation surfaces.
- Restore only the rows and policy state named in the durable backup manifest. Restore deployment
  definitions and Container Apps traffic if they changed.
- Verify rollback directly in Cosmos, then through the mirror and report. Do not declare recovery
  from elapsed time alone.
- Never use **Freshen Turn Times** in the controlled sequence.

## Demo 1 — Frontend application

### Browser target

- **Instance:** Travel app
- **Tabs:** Explore, Profile and Memories, Trips
- **Location:** seeded user session with the planned Barcelona trip

### Sequence and talk track

1. On **Explore**, introduce the multi-agent travel application. Cosmos DB is the operational
   system of record; LangGraph coordinates specialist agents and the Cosmos DB Agent Memory
   Toolkit supports persistent conversational context.
2. Explain that users can discover hotels, restaurants, and activities and build day-by-day trips.
3. Open **Profile and Memories**:
   - persisted profile preferences are explicit user-owned data;
   - inferred memories and summaries come from conversations and add absent or scoped context;
   - inferred memory does not override an overlapping persisted profile preference.
4. Open **Trips**, then the planned Barcelona trip. Point out the existing dates, planning status,
   hotel, restaurants or meals, and activities.
5. Return to **Explore** and ask the assistant to add a concrete hotel, restaurant or meal, or
   activity to the existing planning trip. Breakfast can be the example, not the capability
   boundary.
6. Confirm that the assistant discovers a real candidate and merges only the requested change.
   Verify the same trip ID, dates, planning status, unrelated itinerary fields, and trip count.
7. If zero or multiple planning trips are plausible, show that the assistant clarifies rather than
   creating or mutating a trip.

## Demo 2 — Cosmos, mirroring, and SQL endpoint

### Browser target

- **Instance:** Azure portal and Fabric
- **Tabs:** Cosmos Data Explorer, mirrored database, SQL analytics endpoint
- **Locations:** `TravelAssistant`; mirrored tables; `OptimizationTurns` and
  `OptimizationInsights`

### Sequence and talk track

1. In **Cosmos Data Explorer**, show the operational records that power the application:
   sessions/messages, trips, memories and summaries, checkpoints or node executions, and
   optimization telemetry.
2. Explain that Cosmos serves the live request path and persists agent, user, and trip state.
3. In the **Fabric mirrored database**, show near-real-time replication from Cosmos into OneLake.
   Use the replication status as evidence; do not assume convergence from elapsed time.
4. In the **SQL analytics endpoint**, expand the `TravelAssistant` schema and open:
   - `OptimizationTurns` — observed agent-turn path, complexity, serving model, and token usage;
   - `OptimizationInsights` — flattened analytical results written back for operational use.
5. Explain that analysis begins with observed application behavior and that reverse ETL returns
   small, governed insight rows to Cosmos.

## Demo 3 — Fabric notebook

### Browser target

- **Instance:** Fabric
- **Tab:** Notebook
- **Location:** completed `ConversionFunnelReverseETL` notebook, initially collapsed at the top

### Sequence and talk track

1. Explain the two planes: Cosmos serves the live application; Fabric performs cross-session
   analysis over the mirror.
2. Expand **Read the Mirror**. The notebook reads the SQL analytics endpoint instead of scanning
   the transactional account.
3. Expand **Classify the abandonment cause**. Show the funnel from engaged to searched to planned
   to confirmed and the deterministic cause classification.
4. Expand the measured model-selection counterfactual. It prices observed turns using both the
   serving model and the premium baseline; the measured result is grounded in real token usage.
5. Point out the agent, memory, turn, business, recommendation, and governance sections and the
   reverse-ETL writes to `OptimizationInsights`.
6. Expand **LLM analyst**. The model proposes interpretation and recommendation language, while
   deterministic code owns evidence, allowed action surfaces, acceptance, and financial values.
7. In Prepared mode, show already completed output. Do not run all on stage unless rehearsed.

## Demo 4 — User Data Function

### Browser target

- **Instance:** Fabric
- **Tab:** User Data Function
- **Location:** `optimization-apply-loop`

### Sequence and talk track

1. Show `apply_optimization`. It performs the approved scoped policy-state transition used by the
   Power BI action.
2. Follow the call to the internal status-write function. Show the Cosmos client setup, exact
   policy read, state update, and upsert.
3. Show `revert_optimization`. It uses the same controlled write path with the reverted state.
4. Explain the optimization-apply-loop:
   - recommendation appears in the analytical surface;
   - the presenter applies or reverts through the UDF;
   - Cosmos stores the audited policy state;
   - the running application reads the new state on a later turn;
   - observed traffic is remeasured before a result is claimed.
5. The UDF does not own reset, synthetic traffic generation, recompute, or timestamp maintenance.

## Demo 5 — Power BI and web analytics portal

### Browser target

- **Instance:** Fabric and hosted app
- **Tabs:** Power BI report, web analytics portal
- **Locations:** Power BI Portfolio Overview and Optimizations; portal Overview, Optimizations,
  Model Selection, Memory, Agents, Business, and Governance

### Power BI sequence and talk track

1. Set the Power BI tenant slicer to **Marvel** before the audience sees the report.
2. Open **Portfolio Overview**. Show turns, cost, cache behavior, confirmed trips, cost per
   outcome, optimization counts, and the model distribution.
3. Point out the **Before** state:
   - all controlled turns use the premium model;
   - active policies is `0`;
   - measured saving is blank or **Not measured yet**;
   - estimated saving and the ranked model-selection opportunity are visible.
4. Open **Optimizations**. Show the ranked opportunity, its projected saving, the separate
   recommendation cards, and the Apply/Revert controls. In Prepared mode, describe **Apply** but do
   not select it; Marvel must remain the Before comparison.
5. Change the tenant slicer from **Marvel** to **Analytics**.
6. Return to **Portfolio Overview** and show the prepared **After** state:
   - active policies is `1`;
   - measured saving is `2.8005`;
   - the model distribution includes premium, mini, and nano;
   - the optimized dataset contains 400 controlled turns.
7. Open **Optimizations** again. Show that the ranked opportunity is **Active / Applied**, that
   exactly one Analytics row appears, and that its measured and projected values belong to
   Analytics.
8. Explain that Power BI is an observation and scoped policy-writeback surface. It does not own
   reset, controlled traffic, or recomputation.
9. A missing measurement is **Not measured yet** or blank; `$0.00` means a real completed
   measurement calculated zero.

### Web analytics portal sequence and talk track

Start with **Tenant = Analytics** and **Source = Reverse-ETL (notebook)** so the portal shows the
same prepared After snapshot as Power BI.

1. **Overview:** portfolio metrics, optimization band, model mix, and turn timeline. Call out the
   active Analytics policy and tiered model mix.
2. **Optimizations:** ranked opportunities and reversible governed actions.
3. **Model Selection:** serving-model mix, actual versus baseline cost, complexity tiers, and
   projected volume scenarios.
4. **Memory:** memory types, salience, supersession, and health.
5. **Agents:** per-agent health and costly paths.
6. **Business:** conversion funnel, confirmed trips, cost per outcome, and abandonment causes.
7. **Governance:** current policy state, SLO evidence, measured results, and audit history.

Close by restating the loop: the live application produces operational evidence; Fabric analyzes
the mirror; reverse ETL returns governed insight; a scoped reversible action changes future
behavior; and measurement determines whether the optimization was successful.
