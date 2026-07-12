# Travel Multi-Agent Workshop - Exercises

This is the starting point for the Travel Multi-Agent Workshop. Here you'll build a  multi-agent travel assistant system step-by-step, learning to create specialized AI agents that work together using Python, LangGraph, Azure OpenAI, and Azure Cosmos DB.

## Getting Started

Follow the workshop modules to build your multi-agent travel planning system from the ground up. The workshop includes step-by-step guidance, code examples, and hands-on activities to help you master design patterns for multi-agent applications.

Get started here 👉  **[Start the Workshop](workshop/Home.md)**

## Deployment & run options

`azd provision` deploys the **data + AI infra** — an Azure Cosmos DB account (`TravelAssistant`
database) and an Azure AI Foundry (AIServices) account with the **gpt-5.1** chat model,
`text-embedding-3-small`, and the optimization-tier models (`gpt-5-nano`, `gpt-5-mini`). The
post-provision hook writes `python/.env` + `mcp_server/.env`, creates a virtualenv, and seeds Cosmos.

During the workshop the application (Travel API, MCP server, Angular frontend) **runs locally** against
that infra — see `frontend/README.md` and Module 00. Running locally keeps cost low and avoids a
container build/deploy every time you change code.

### Optional deployment flags

Set with `azd env set <NAME> <value>` before `azd provision`:

| Flag (env var) | Default (01_exercises) | Effect |
|---|---|---|
| `deployAnalytics` (`DEPLOY_ANALYTICS`) | **true** | Provisions the analytics/optimization Cosmos containers (`OptimizationPolicies`, `OptimizationTurns`, `OptimizationInsights`, `Configuration`) used by **Modules 07 (Analytics)** and **08 (Optimization)**. Set `false` if you are not doing those modules, for a leaner, cheaper base deployment. |
| `deployHostedApp` (`DEPLOY_HOSTED_APP`) | **false** | Off by default — the workshop runs the app **locally** (`azd provision` + three terminals). To deploy a hosted instance on Azure Container Apps instead: `azd env set DEPLOY_HOSTED_APP true`, **uncomment the `services:` block in `azure.yaml`**, then `azd up`. (The complete solution in `02_completed` ships with hosting enabled by default.) |

```powershell
# Example: skip the analytics containers (not doing Modules 07/08)
azd env set DEPLOY_ANALYTICS false
azd provision
```

> **AI models & pricing:** `azd up` deploys `gpt-5.1`, `gpt-5-mini`, and `gpt-5-nano`, and
> seeds their token prices into the Cosmos `Configuration` container so the app, the Fabric
> notebook, and the Power BI report all cost turns off the same numbers. **If you change the
> deployed models, add the new model's price** to `python/data/model_pricing.json` — see
> **[analytics/docs/model-pricing.md](../analytics/docs/model-pricing.md)** for the models used
> by default, the price format, and how to find a model's price.

## Project Structure

```
01_exercises/
├── python/       # Main Python application
│   ├── data/     # Sample data for hotels, restaurants, activities
│   └── src/      # Application source code
├── frontend/     # Angular web application
├── infra/        # Azure infrastructure as code
├── mcp_server/   # MCP server
└── workshop/     # Workshop modules and instructions
```