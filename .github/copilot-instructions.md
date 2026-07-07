# Copilot Instructions — Travel Multi-Agent Workshop

A workshop that builds a multi-agent travel assistant with **Python + LangGraph + Azure OpenAI + Azure Cosmos DB**, an **Angular** frontend, and a **FastMCP** tool server.

## Repository layout

- `01_exercises/` — the workshop starting point (has scaffolding + `workshop/` module docs `Module-00`…`Module-07` and an `evaluation/` harness).
- `02_completed/` — the fully implemented reference solution. **Make behavioral changes here** unless a task explicitly targets the exercises.

Both trees mirror the same structure: `python/` (agents + API), `mcp_server/`, `frontend/`, `infra/` (Bicep), `azure.yaml`, `requirements.txt`.

## Architecture (read multiple files to understand)

Three processes run together; the frontend proxies `/api` and MCP calls:

1. **Travel API** — `python/src/app/travel_agents_api.py` (FastAPI). Entry endpoint `POST .../chat/...` runs the LangGraph graph. Endpoints are keyed by `tenantId` / `userId` / `sessionId` throughout.
2. **Agent graph** — `python/src/app/travel_agents.py`. `build_agent_graph()` wires a `StateGraph(MessagesState)`: `START → orchestrator`, which routes to specialist nodes `hotel`, `activity`, `dining`, `itinerary_generator`, `summarizer`, plus a `human` interrupt node. Specialists answer one turn then edge back to `human`; the next user turn re-enters at `orchestrator` (deliberate, to avoid loops on stale `activeAgent`).
3. **MCP server** — `mcp_server/mcp_http_server.py` (FastMCP over HTTP, default `:8080`). Exposes the tools agents call: memory (`store_user_memory`, `recall_memories`), summarization, `discover_places`, trip CRUD, and the **`transfer_to_<agent>` routing tools**. Agents load these via `langchain_mcp_adapters` and filter by name prefix.

**Routing convention:** an agent hands off by calling a `transfer_to_<name>` tool; graph code strips the `transfer_to_` prefix to compute the next node (`get_active_agent`). The active agent is persisted on the session doc and also recovered from Cosmos on cold start.

**Persistence** — `python/src/app/services/azure_cosmos_db.py` holds all data access. Database `TravelAssistant` with containers: `Sessions`, `Messages`, `Summaries`, `Memories`, `ApiEvents`, `Debug`, `Places`, `Trips`, `Users`, `Checkpoints`. Most containers use a **hierarchical partition key `[tenant_id, user_id, session_id]`**. LangGraph state is checkpointed via `CosmosDBSaver` into `Checkpoints`. `Places` supports vector/hybrid search (`query_places_hybrid`, `query_places_filtered`).

**Models** — `python/src/app/services/azure_open_ai.py` builds a shared LangChain `AzureChatOpenAI` `model` and embeddings, authenticating with `DefaultAzureCredential` (token provider, not keys, in the deployed path).

## Conventions

- **Agent prompts live in `python/src/app/prompts/*.prompty`** and are loaded by name with `load_prompt(agent_name)` — edit the `.prompty` file, don't hardcode prompt text.
- **Memory is a first-class subsystem:** preferences are extracted from messages, conflicts resolved (`memory_conflict_resolution.prompty`), and stored/superseded rather than overwritten. Summarizer auto-runs (~every 10 turns) to compress message spans.
- MCP tools are decorated `@mcp.tool()` + `@langsmith.traceable`; new agent-callable capability = a new tool in `mcp_http_server.py`, not a direct DB call from the agent.
- Cosmos containers are lazily initialized module globals in `azure_cosmos_db.py`; reuse the existing accessor functions instead of creating new clients.

## Build / run / test

**Deploy everything (provisions Azure + seeds data):** from `02_completed/`, `azd auth login` then `azd up`. Post-provision writes `python/.env` and `mcp_server/.env` and seeds Cosmos via `cd python; python data/seed_data.py`.

**Local dev — three terminals from `02_completed/`** (venv created by `azd up`):

```powershell
# 1. MCP server
.\venv\Scripts\Activate.ps1; cd mcp_server; $env:PYTHONPATH="..\python"; python mcp_http_server.py
# 2. Travel API
.\venv\Scripts\Activate.ps1; cd python; uvicorn src.app.travel_agents_api:app --reload --host 0.0.0.0 --port 8000
# 3. Frontend (Angular 19, proxies to the API)
cd frontend; npm install; npm start
```

URLs: API docs `:8000/docs`, MCP `:8080/docs`, frontend `:4200`.

**Frontend** (`frontend/`): `npm run build`, `npm run lint`, `npm test` (Karma/Jasmine). `npm test` runs the whole suite; target a single spec with `ng test --include=src/app/<path>/<name>.component.spec.ts`.

**Evaluation** (`01_exercises/evaluation/`, LLM-as-judge; requires the API/services running): run an individual suite directly, e.g. `python e2e_evaluation.py`, `python routing_evaluation.py`, or `python tool_usage_evaluation.py`.

## Environment

Config comes from `.env` files (`python/.env`, `mcp_server/.env`), loaded with `load_dotenv(override=False)` — see `python/.env.example`. Key vars: `COSMOSDB_ENDPOINT`, `COSMOS_DB_DATABASE_NAME`, `AZURE_OPENAI_ENDPOINT`/`_DEPLOYMENT`/`_EMBEDDING_DEPLOYMENT`/`_API_VERSION`, `MCP_SERVER_BASE_URL`, `MCP_AUTH_TOKEN`. Optional LangSmith tracing via `LANGCHAIN_*`. Never commit real `.env` values.
