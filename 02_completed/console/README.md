# Agent Optimization Console

A small, provided web dashboard for the **Analytics & Optimization** modules. It renders the
**agents × dimensions** view of ADR-0010: an **agent scorecard**, the engine's **discovered
opportunities**, and the **C1–C5 human-in-the-loop** governed actions.

It is a **teaching surface** — in the workshop you write the loop *logic* (the engine + API),
not this UI.

## Files (kept small, one job each)

| File | Role |
|---|---|
| `index.html` | the shell — sections + inputs, no logic |
| `console.css` | the dark theme + layout |
| `api.js` | `OptimizationApi` — a thin client for the endpoints |
| `console.js` | the view logic (renders the DOM; render fns are exported for testing) |

## Run it

The console is static files. Serve them on their own port (kept separate from the `:4200`
travel app and the `:8000` API):

```powershell
# from 02_completed
python -m http.server 8050 --directory console
```

Then open <http://localhost:8050>. In the top bar set **API** (default `http://localhost:8000`),
**Tenant** (the tenant you drove traffic with), and **Actor** (who is taking governed actions —
recorded in the audit trail). Click **Refresh**.

> Serve over **http** (not `file://`) — the console uses ES modules, which browsers only load over http.

## What it shows

- **Agent scorecard** — each agent scored across the dimensions node-grain telemetry can measure
  (cost efficiency, model selection, workflow efficiency); the rest are listed with the signal they
  still need. Reads `NodeExecutions`.
- **Discovered opportunities** — surfaced by the engine (detect → project → propose → guardrail →
  rank). Savings are **engine-computed**, not the analyst's claim. Each card shows its SLO gate and
  governed state, and offers **Review diff / Approve / Reject / Attest deploy / Confirm revert**.
- **Governance** — the **SLO / confidence / min-effect policy** the engine gates against (C3) and a
  **declare-a-domain-schema** form the engine binds & validates through the fail-closed SDK (C5).
- **Audit trail** — every governed action, attributed and timestamped (C1, C4).

## Endpoints it calls (agent-centric surface)

- `GET  /optimizations/agent/{tenant}/scorecard`
- `GET  /optimizations/agent/{tenant}/opportunities`
- `GET  /optimizations/agent/{tenant}/opportunity/{id}/diff`
- `GET  /optimizations/agent/{tenant}/decisions`
- `POST /optimizations/agent/{tenant}/decision`  — approve · reject · attest · confirm-revert
- `GET/POST /optimizations/agent/{tenant}/slo`
- `GET/POST /optimizations/agent/{tenant}/schema`

Backed by `src/app/optimization_agent_api.py` (the router), `src/app/engine/` (the analysis engine),
`src/app/services/node_executions.py` (telemetry), and `src/app/services/optimization_governance.py`
(the audit store). The API allows all origins, so the console can call it from `:8050`.

## Requirements

- The Travel API running with the agent-centric router mounted (it is, by default).
- `NodeExecutions` telemetry for the tenant (captured automatically on the streaming completion path).
