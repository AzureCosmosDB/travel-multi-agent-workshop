# Travel Multi-Agent Workshop

## Overview

This workshop walks through how to build a multi-agent travel assistant system using Python, LangGraph, Azure Foundry, and Azure Cosmos DB. Here, you'll create specialized AI agents that work together to help users plan travel arrangements and learn about agent memory orchestration. The workshop concludes with **optional modules on agent analytics and optimization** — instrumenting your agents, surfacing cost and quality insights, and applying (and auto-reverting) reversible optimizations — plus a **Microsoft Fabric** analytics and reverse-ETL module.

### What You'll Build

By the end of this workshop, you'll have created a complete travel planning application featuring:

- **Multiple specialized sgents**: Hotel booking agent, dining recommendations agent, activity planning agent, and more
- **Intelligent orchestration**: A coordinator agent that manages interactions between specialized agents
- **Memory system**: Persistent memory storage using Azure Cosmos DB to remember user preferences and past interactions
- **Modern web interface**: An Angular frontend that provides an intuitive chat interface
- **API layer**: A FastAPI backend that orchestrates all agent interactions

### Memory layer

Memory is provided by the [`azure-cosmos-agent-memory`](https://pypi.org/project/azure-cosmos-agent-memory/) PyPI package. The toolkit auto-creates its Cosmos DB `memories`, `memories_turns`, `memories_summaries`, and `counter` containers on first run via `connect_cosmos()`. Auto-summarization thresholds are controlled by environment variables (`FACT_EXTRACTION_EVERY_N`, `DEDUP_EVERY_N`, `THREAD_SUMMARY_EVERY_N`, `USER_SUMMARY_EVERY_N`). Memory records are partitioned by `(user_id, thread_id)`. Memory prompts ship inside the package, so no `.prompty` files for memory are needed in this repo.

### Learning Objectives

- Understand multi-agent architecture patterns and design principles
- Learn to build agents using LangGraph framework with Azure OpenAI
- Implement agent specialization and tool integration
- Add intelligent memory systems to enhance agent interactions
- Practice observability and experimentation techniques
- Deploy and manage AI applications on Azure

## Getting Started

This repository contains two main directories:

### 📚 **01_exercises** - The Workshop
Navigate to this folder to follow along with the step-by-step workshop modules. Start here if you want to build the solution from scratch and learn each concept progressively.

Get started here 👉 **[Start the Workshop](01_exercises/workshop/Home.md)**

### ✅ **02_completed** - The complete solution
Navigate to this folder to access the fully implemented solution. Use this if you want to see the end result or deploy the complete application.

## Deployment Instructions for Complete Solution (02_completed)

To deploy the complete travel multi-agent assistant to your Azure account, follow these steps:

1. **Clone the Repository**: Start by cloning this repository to your local machine.
    ```bash
    git clone https://github.com/AzureCosmosDB/travel-multi-agent-workshop.git
    cd 02_completed
    ``` 

2. **Install Prerequisites**: Ensure you have the following installed:
   - [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli)
   - [Azure Developer CLI (azd)](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd)
   - [Python 3.11+](https://www.python.org/downloads/)
   - [Node.js and npm](https://nodejs.org/en/download/)

3. **Login to Azure**: Use the Azure CLI to log in to your Azure account.
    ```bash
    azd auth login
    ```
4. **Run azd up**: Navigate to the `travel-multi-agent-workshop/02_completed/infra` directory and run the following command to deploy the solution:
    ```bash
    azd up
    ```
   This command will provision all necessary Azure resources and seed the database. It may take several minutes to complete.

## Running Locally After Deployment

Once deployed, the app runs locally in three terminals (MCP server, Travel API, Angular frontend). The step-by-step instructions live with each path rather than here:

- **Workshop (`01_exercises`):** start the API and frontend in **[Module 00](01_exercises/workshop/Module-00.md)**, then the MCP server in **[Module 01](01_exercises/workshop/Module-01.md)**.
- **Complete solution (`02_completed`):** see **[02_completed/README.md → Local dev](02_completed/README.md#local-dev-three-terminals)**.

