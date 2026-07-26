# Travel Multi-Agent Workshop - Complete Solution

This is the complete implementation of the Travel Multi-Agent Workshop. Here you'll find a fully functional multi-agent travel assistant system with specialized AI agents that work together using Python, LangGraph, Azure OpenAI, and Azure Cosmos DB.

## Getting Started

This complete solution demonstrates the final result of the workshop with all modules implemented. You can deploy this directly to Azure or use it as a reference while working through the workshop exercises.

Deploy the complete solution 👉  **[Deploy to Azure](#deploy-to-azure)**

📖 **[User Guide](./USER_GUIDE.md)** — how to use the travel assistant, interact with agents, manage memories, and get the best results.

## Deploy to Azure

To deploy the complete travel multi-agent assistant to your Azure account:

1. **Clone the repository** and switch to this folder:
   ```bash
   git clone https://github.com/AzureCosmosDB/travel-multi-agent-workshop.git
   cd travel-multi-agent-workshop/02_completed
   ```
2. **Install prerequisites:**
   - [Azure CLI](https://docs.microsoft.com/cli/azure/install-azure-cli)
   - [Azure Developer CLI (azd)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
   - [Python 3.11+](https://www.python.org/downloads/)
   - [Node.js 18+ and npm](https://nodejs.org/en/download/)
3. **Log in to Azure:**
   ```bash
   azd auth login
   ```
4. **Provision and deploy** — `azd up` provisions all Azure resources, seeds Cosmos DB, and (because `deployHostedApp` defaults to **true** here) deploys the hosted app:
   ```bash
   azd up
   ```
   Provisioning takes several minutes. See [Deployment & run options](#deployment--run-options) below for the optional flags and the local three-terminal flow.

## Deployment & run options

`azd provision` deploys the **data + AI infra** — an Azure Cosmos DB account (`TravelAssistant`
database) and an Azure AI Foundry (AIServices) account with the **gpt-5.1** chat model,
`text-embedding-3-small`, and the optimization-tier models (`gpt-5-nano`, `gpt-5-mini`). The
post-provision hook writes `python/.env` + `mcp_server/.env`, creates a virtualenv, and seeds Cosmos.

The application processes (Travel API, MCP server, Angular frontend) **run locally** against that infra
— see [Local dev](#local-dev-three-terminals) below. This keeps per-attendee cost low and avoids a
container build/deploy on every change.

### Optional deployment flags

Both are azd environment variables set with `azd env set <NAME> <value>` before `azd provision`/`azd up`:

| Flag (env var) | Default (02_completed) | Effect |
|---|---|---|
| `deployAnalytics` (`DEPLOY_ANALYTICS`) | **true** | Provisions the analytics/optimization Cosmos containers (`OptimizationPolicies`, `OptimizationTurns`, `OptimizationInsights`, `Configuration`) **and the Microsoft Fabric F2 capacity** used by **Modules 07 (Analytics)**, **08 (Optimization)**, and **09 (Fabric Analytics & Reverse-ETL)**. Set `false` for a leaner base deployment; the app still self-provisions the containers at runtime if those features are exercised. |
| `deployGsi` (`DEPLOY_GSI`) | **false** | Provisions an alternative **provisioned-throughput** Cosmos DB account with a `TripsByDestination` **global secondary index** and seeds ~25K trips — an optional demonstration of the provisioned-throughput + GSI scaling pattern. Not required by any module; leave `false` for the standard deployment. |
| `deployHostedApp` (`DEPLOY_HOSTED_APP`) | **true** | Deploys the app as **hosted Azure Container Apps** (frontend + API + MCP, with ACR + Container Apps environment + Log Analytics). `azd up` builds the three images and deploys them; the public frontend URL is printed as `FRONTEND_URI`. Set `false` to skip hosting and run the app locally instead (`azd provision` only). |

> This is the **complete/demo** solution, so both flags are **on by default** — `azd up` gives you a
> fully hosted, publicly reachable app. Run `azd provision` (not `up`) if you only want the infra and
> prefer the local three-terminal flow.

```powershell
# Example: skip the analytics containers
azd env set DEPLOY_ANALYTICS false
azd provision
```

> **AI models & pricing:** `azd up` deploys `gpt-5.1`, `gpt-5-mini`, and `gpt-5-nano`, and
> seeds their token prices into the Cosmos `Configuration` container so the app, the Fabric
> notebook, and the Power BI report all cost turns off the same numbers. **If you change the
> deployed models, add the new model's price** to `python/data/model_pricing.json` — see
> **[analytics/docs/model-pricing.md](../analytics/docs/model-pricing.md)** for the models used
> by default, the price format, and how to find a model's price.

### Local dev (three terminals)

From `02_completed/` after `azd provision` (venv `.venv-travel` is created for you):

```powershell
# 1. MCP server
.\.venv-travel\Scripts\Activate.ps1; cd mcp_server; $env:PYTHONPATH="..\python"; python mcp_http_server.py
# 2. Travel API
.\.venv-travel\Scripts\Activate.ps1; cd python; uvicorn src.app.travel_agents_api:app --reload --host 0.0.0.0 --port 8000
# 3. Frontend (Angular, proxies /api to the API)
cd frontend; npm install; npm start
```

URLs: API docs `:8000/docs`, MCP `:8080`, frontend `:4200`.

## Memory layer

Memory is provided by the [`azure-cosmos-agent-memory`](https://pypi.org/project/azure-cosmos-agent-memory/) SDK (`pip install azure-cosmos-agent-memory`). The toolkit auto-creates its Cosmos DB `memories`, `memories_turns`, and `memories_summaries` containers on first run, so no Bicep container resources are needed for memory. Every 10 chat turns, a background auto-flush produces summaries, facts, and a `user_summary`. Memory records are partitioned by `(user_id, thread_id)`; `tenantId` remains for sessions, messages, and trips, but is no longer part of memory records. Memory prompts ship inside the toolkit, so `preference_extraction.prompty`, `memory_conflict_resolution.prompty`, and `summarizer.prompty` have been removed from this repo.

## Project Structure

```
02_completed/
├── python/       # Fully implemented Python application
│   ├── data/     # Complete sample data with seed scripts
│   └── src/      # Complete application source code
├── frontend/     # Complete Angular web application
├── infra/        # Complete Azure infrastructure as code
└── mcp_server/   # Complete MCP server
```

This structure contains the complete, production-ready implementation of all workshop modules with full multi-agent functionality, memory systems, and Azure integrations.