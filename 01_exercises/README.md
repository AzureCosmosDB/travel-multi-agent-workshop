# Travel Multi-Agent Workshop - Exercises

This is the starting point for the Travel Multi-Agent Workshop. Here you'll build a  multi-agent travel assistant system step-by-step, learning to create specialized AI agents that work together using Python, LangGraph, Azure OpenAI, and Azure Cosmos DB.

## Getting Started

Follow the workshop modules to build your multi-agent travel planning system from the ground up. The workshop includes step-by-step guidance, code examples, and hands-on activities to help you master design patterns for multi-agent applications.

Get started here 👉  **[Start the Workshop](workshop/Home.md)**

## Deployment

Deployment and all `azd` options — including the optional `deployAnalytics`, `deployGsi`, and `deployHostedApp` flags — are covered step-by-step in **[Module 00 – Deployment and Setup](workshop/Module-00.md)**. During the workshop the application (Travel API, MCP server, Angular frontend) **runs locally** against the provisioned Azure data + AI infra, which keeps cost low and avoids a container build/deploy on every code change.

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