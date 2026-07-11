# Parking Lot — deferred work & future fixes

A single place to record work that is **intentionally deferred** (blocked on an external
dependency, a platform gap, or a decision we've chosen to postpone) so it isn't lost and
can be picked up the moment its blocker clears. This complements the ADRs in
[`adr/`](./adr): ADRs record decisions we've *made*; this file tracks work we've *parked*.

**How to use:** add an entry per parked item using the template at the bottom. When a
blocker clears, move the item into implementation (and, if it changes a decision, write or
update an ADR). Keep entries short and link to the code/spike that proves the approach.

---

## 1. Fabric auto DMTS connection (Cosmos mirroring) — *parked, demo-only today*

- **Status:** Parked. The workshop **ships with the manual portal connection step**
  (Fabric portal → New → Mirrored Azure Cosmos DB → Organizational account / OAuth2). The
  automated path is preserved but **not** wired into `provision_fabric.py`.
- **Goal:** fully automate the Cosmos DB OAuth2 **connection** creation so the entire
  Fabric provisioning flow (capacity → workspace → identity → RBAC → **connection** →
  mirror → notebook → report) is hands-free.
- **What works (validated 2026-07-11, MSIT):**
  - Creating the connection via the DMTS gateway datasource endpoint returns **200**.
  - The embedded credential must use a **Cosmos-audience** access token
    (`az account get-access-token --resource https://cosmos.azure.com`), not a Fabric one —
    this was the audience mismatch that blocked earlier attempts.
  - With the correct data-plane RBAC (`readMetadata` + `readAnalytics` on the connection
    identity), a mirror can use the connection.
  - Spike preserved at
    [`../fabric/experimental/create_oauth_connection.py`](../fabric/experimental/create_oauth_connection.py).
- **What's blocked (why it's parked):**
  1. **No refresh token.** The embedded token has no refresh token, so the connection
     dies at token expiry (~1 hour). A durable connection needs a refresh token the
     Fabric gateway OAuth app can redeem.
  2. **MSIT-only endpoint.** The DMTS endpoint is the MSIT redirect; production differs.
- **Trigger to revisit:** Fabric gateway team supports audience + refresh on the automated
  path. Re-run the spike, confirm a mirror survives past token expiry, then wire an
  optional `--auto-connection` path into `provision_fabric.py` with the manual step as the
  fallback.
- **References:** `analytics/fabric/README.md` (connection section);
  `analytics/fabric/provision_fabric.py` (Phase 2).

---

## Entry template

```
## N. <short title> — *<status>*

- **Status:** Parked / In progress / Ready when unblocked.
- **Goal:** what we're trying to achieve.
- **What works:** validated pieces (+ link to the spike/code).
- **What's blocked:** the specific blocker(s) and why.
- **Trigger to revisit:** the event/date that unblocks this.
- **References:** files, docs, ADRs, external threads.
```
