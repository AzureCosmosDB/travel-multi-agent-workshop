# v2 Evaluation Harness (supervisor + sub-agents-as-tools)

These evaluations target the **`agent_memory_toolkit_v2`** architecture, where a
single **supervisor** ReAct agent delegates to sub-agents exposed as **tools**
(`find_places`, `create_or_update_itinerary`). This differs fundamentally from
the classic suite in `01_exercises/evaluation/`, which assumed a graph of
specialist *nodes* (`orchestrator → hotel / dining / activity /
itinerary_generator`).

## Why a separate harness

| | Classic (`01_exercises/evaluation`) | v2 (`analytics/evaluation`) |
|---|---|---|
| Topology | orchestrator + 5 specialist **nodes** | supervisor + sub-agent **tools** |
| "Routing" means | which specialist **node** ran | which sub-agent **tool** the supervisor delegated to |
| Signal source | `on_chain_start` node names | `on_tool_start` tool names |
| Backend | uploads datasets to **LangSmith** (`LANGCHAIN_API_KEY` required) | **fully local**, no LangSmith account |
| Imports solution from | `../python` (empty student scaffold) | `02_completed/python` (reference solution) |

Running fully local (no trace upload) matches the analytics initiative's
Cosmos-first, source-pluggable philosophy (ADR-0003) and keeps the eval a fast,
dependency-light regression gate.

## Delegation model

On v2 the hotel / activity / dining specialists collapse into a single
`find_places` tool (called with `aspects`). So the routing granularity is:

- **`find_places`** — any hotel / activity / dining / place search.
- **`create_or_update_itinerary`** — build or save a day-by-day trip. An
  itinerary request legitimately fans out to `find_places` first and then
  `create_or_update_itinerary`, so correctness is **membership-based** (did the
  expected sub-agent get delegated to at all), not first-delegate.
- **`supervisor`** — the supervisor answered directly without delegating.

## Running

Prerequisites: the v2 venv, and the **MCP server running on :8080** (the
in-process graph calls MCP tools). No API server needed — the graph is driven
directly.

```powershell
# terminal 1 — MCP server
cd 02_completed/mcp_server; $env:PYTHONPATH="..\python"; python mcp_http_server.py

# terminal 2 — run the eval from repo root
$env:PYTHONPATH="02_completed\python"; python analytics\evaluation\routing_evaluation_v2.py
```

Exit code is 0 when all delegations are correct, 1 otherwise.

## Notes on non-determinism

Like the classic suite, a small number of borderline prompts are
non-deterministic: for some phrasings the supervisor answers a place query from
its own knowledge instead of delegating to `find_places`. The dataset uses clear
"Find …" search intents to keep the gate stable; expect the occasional single
flaky case on re-run (re-run to confirm), rather than treating it as a
regression.

## Status / follow-ups

- **`routing_evaluation_v2.py`** — implemented and validated (7/7 delegations on
  the reference solution).
- **tool-usage** and **end-to-end answer-quality** evals: the classic versions
  are less architecture-coupled (they assert tools-called / judge answer text)
  and can be ported to this local harness pattern next; tracked as a follow-up.
