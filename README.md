# Travel Multi-Agent Workshop

## Overview

This workshop walks through how to build a  multi-agent travel assistant system using Python, LangGraph, Azure OpenAI, and Azure Cosmos DB. Here, you'll create specialized AI agents that work together to help users plan  travel arrangements and learn about agent memory orchestration.

### What You'll Build

By the end of this workshop, you'll have created a complete travel planning application featuring:

- **Multiple specialized sgents**: Hotel booking agent, dining recommendations agent, activity planning agent, and more
- **Intelligent orchestration**: A coordinator agent that manages interactions between specialized agents
- **Memory system**: Persistent memory storage using Azure Cosmos DB to remember user preferences and past interactions
- **Modern web interface**: An Angular frontend that provides an intuitive chat interface
- **API layer**: A FastAPI backend that orchestrates all agent interactions

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

## Setting up local development

When you deploy this solution, it automatically configures `.env` files with the required Azure endpoints and authentication tokens for both the main application and MCP server.

To run the solution locally after deployment:

### Terminal 1 - Start the MCP server:

Open a new terminal, navigate to the `02_completed` directory, then run:

**Linux/macOS:**
```bash
source venv/bin/activate
cd mcp_server
PYTHONPATH=../python python mcp_http_server.py
```

**Windows (PowerShell):**
```bash
.\venv\Scripts\Activate.ps1
cd mcp_server
$env:PYTHONPATH="..\python"
python mcp_http_server.py
```

**Windows (Command Prompt):**
```cmd
venv\Scripts\activate.bat
set PYTHONPATH=../python && python mcp_http_server.py
```

### Terminal 2 - Start the Travel API:

Open a new terminal, navigate to the `02_completed` directory, then run:

**Linux/macOS:**
```bash
source venv/bin/activate
cd python
uvicorn src.app.travel_agents_api:app --reload --host 0.0.0.0 --port 8000
```

**Windows (PowerShell):**
```powershell
venv\Scripts\Activate.ps1
cd python
uvicorn src.app.travel_agents_api:app --reload --host 0.0.0.0 --port 8000
```

**Windows (Command Prompt):**
```cmd
venv\Scripts\activate.bat
uvicorn src.app.travel_agents_api:app --reload --host 0.0.0.0 --port 8000
```

### Terminal 3 - Start the Frontend:

Open a new terminal, navigate to the `02_completed\frontend` folder, then run:

**All platforms:**
```bash
npm install
npm start
```

Access the applications:

- Travel API: [http://localhost:8000/docs](http://localhost:8000/docs)
- MCP Server: [http://localhost:8080/docs](http://localhost:8080/docs)
- Frontend: [http://localhost:4200](http://localhost:4200/)