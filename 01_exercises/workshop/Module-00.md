# Module 00 - Deployment and Setup

**[< Home](./Home.md)** - **[Creating Your First Agent >](./Module-01.md)**

## Introduction

Welcome to the Travel Assistant Multi-Agent Workshop! In this module, you'll set up your development environment, seed the database with initial data, and verify that both the API server and frontend are running correctly.

## Learning Objectives

- Configure Azure authentication and environment settings
- Provision Azure resources using Azure Developer CLI (azd)
- Verify deployed resources in the Azure Portal
- Start the API server using Uvicorn
- Launch the frontend Angular application
- Verify data in Cosmos DB containers
- Explore the frontend interface

## Module Exercises

1. [Activity 1: Set Up Azure Resources](#activity-1-set-up-azure-resources)
2. [Activity 2: Verify Resources in Azure Portal](#activity-2-verify-resources-in-azure-portal)
3. [Activity 3: Start the API Server](#activity-3-start-the-api-server)
4. [Activity 4: Launch the Frontend](#activity-4-launch-the-frontend)
5. [Activity 5: Verify Your Setup](#activity-5-verify-your-setup)

---

## Activity 1: Set Up Azure Resources

In this activity, you'll use the Azure Developer CLI (azd) to authenticate, configure your environment, and provision all required Azure resources for the workshop.

### Prerequisites

Before you begin, ensure you have:

- Azure subscription with appropriate permissions to create resources
- Azure tenant ID and subscription ID
- [Azure Developer CLI (azd)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) installed
- Python 3.11 or higher installed
- Node.js 18 or higher installed

### Step 1: Get the repository and Navigate to the Workshop Directory

Open your terminal and Clone the Repository.

```bash
git clone https://github.com/AzureCosmosDB/travel-multi-agent-workshop.git
```

Navigate to the workshop directory:

**macOS/Linux:**
```bash
cd ~/travel-multi-agent-workshop/01_exercises
```

**Windows (PowerShell):**
```powershell
cd ~\travel-multi-agent-workshop\01_exercises
```

### Step 2: Configure Azure Authentication

First, ensure you're logged out of any previous Azure sessions, then log in with your workshop credentials:

```bash
azd auth logout
azd auth login --tenant-id <TENANT_ID>
```

Replace `<TENANT_ID>` with your Azure tenant ID.

> **Note:** A browser window will open for authentication. Complete the sign-in process.

### Step 3: Set Environment Variables

**MacOS**

Configure your Azure subscription and tenant ID:

```bash
azd env set AZURE_SUBSCRIPTION_ID <SUBSCRIPTION_ID>
azd env set AZURE_TENANT_ID <TENANT_ID>
```

Replace:
- `<SUBSCRIPTION_ID>` with your Azure subscription ID
- `<TENANT_ID>` with your Azure tenant ID

You'll be prompted for:

1. **Environment name**: Enter a unique name (e.g., `alias-travel`)
   - Use lowercase letters, numbers, and hyphens only
   - Must be globally unique


**Windows**

```bash
az logout
az login --tenant <TENANT_ID>
```

### Step 4: Navigate to Infrastructure Directory

Navigate to the infrastructure directory:

**macOS/Linux:**
```bash
cd infra
```

**Windows (PowerShell):**
```powershell
cd infra
```

### Step 5: Provision Azure Resources

Now, provision all required Azure resources:

```bash
azd up
```

You'll be prompted for:

1cd ... **Azure location**: Select a region (e.g., `eastus`, `westus2`, `westeurope`)
   - Choose a region close to you for better performance

### What Happens During Provisioning?

The `azd up` command will:

✅ Create an Azure resource group: rg-`EnvironmentName`  
✅ Deploy Azure Cosmos DB with three containers (Users, Places, Memories)  
✅ Deploy Azure OpenAI with GPT-4 and text-embedding-ada-002 models  
✅ Configure managed identity and role assignments  
✅ Create a Python virtual environment (`.venv-travel`)  
✅ Install all Python dependencies from `requirements.txt`  
✅ Seed Cosmos DB with initial data:
   - 4 users (Tony Stark, Steve Rogers, Peter Parker, Bruce Banner)
   - ~2,900 places (hotels, restaurants, activities across multiple cities)
   - 10 pre-existing memories

### Expected Output

You should see output like:

```
Provisioning Azure resources (azd up)
Provisioned 1/12 resources.
Provisioned 2/12 resources.
...
Provisioned 12/12 resources.

✅ Environment file created at ./python/.env
✅ Environment file created at ./mcp_server/.env

═══════════════════════════════════════════════════════════════
📦 Setting up Python virtual environment...
═══════════════════════════════════════════════════════════════

Creating Python virtual environment with python3.11...
Activating virtual environment...
Active Python version: Python 3.11.x
Installing Python dependencies from requirements.txt...

═══════════════════════════════════════════════════════════════
📊 Loading data into Cosmos DB...
═══════════════════════════════════════════════════════════════

Seeding users...
Seeding places...
Seeding memories...

✅ Setup complete!
```

**Provisioning typically takes 10-15 minutes.** The process creates all Azure resources and configures your local development environment.

> **Note:** The Python virtual environment (`.venv-travel`) and environment files (`.env`) are created in the parent `01_exercises` directory, not in the `infra` folder.

### Step 6: Open Visual Studio Code

Once provisioning is complete, navigate back to the exercises directory and open the project in VS Code:

**macOS/Linux:**
```bash
cd ..
code .
```

**Windows (PowerShell):**
```powershell
cd ..
code .
```

When prompted, click **Yes, I trust the authors** to trust the workspace.

![Testing_3](./media/Module-00/Test-3.png)

---

## Activity 2: Verify Resources in Azure Portal

Now that resources are provisioned, let's verify they were created correctly in the Azure Portal.

### Step 1: Open Azure Portal

Open your browser and navigate to: **https://portal.azure.com**

Sign in with the same credentials you used for `azd auth login`.

### Step 2: Find Your Resource Group

1. In the search box at the top of the Azure Portal, type **`resource groups`**
2. Click on **Resource groups** from the results
3. Find and open the resource group that starts with **`rg-EnvironmentName`** (followed by your environment name)

> **Note:** If the resource group doesn't appear immediately, wait a moment and refresh the page.

### Step 3: Verify Deployments

1. In your resource group, click on **Deployments** in the left menu under **Settings**
2. Verify that all deployments completed successfully

![Testing_1](./media/Module-00/Test-1.png)

Your screen should look like this:

![Testing 2](./media/Module-00/Test-2.png)

### Step 4: Verify Resources

In the **Overview** tab of your resource group, you should see the following resources:

- **Azure Cosmos DB account** (starts with `cosmos-`)
- **Azure OpenAI service** (starts with `aoai-`)
- **User Assigned Managed Identity** (starts with `id-`)
- **Application Insights** (optional, starts with `appi-`)

If all resources are present and deployments are successful, you're ready to continue!

> **Tip:** Keep the Azure Portal open in a browser tab - you'll use it to verify data in Activity 5.

## Activity 3: Start the API Server

Let's start the backend API server.

### Step 1: Activate the Virtual Environment

The `azd up` command created a virtual environment named `.venv-travel` in the `01_exercises` directory. First, navigate back to the exercises directory, then activate it:

**macOS/Linux:**
```bash
cd ~/travel-multi-agent-workshop/01_exercises
source .venv-travel/bin/activate
```

**Windows (PowerShell):**
```powershell
cd ~\travel-multi-agent-workshop\01_exercises
.\.venv-travel\Scripts\Activate.ps1
```

You should see **(.venv-travel)** appear in your terminal prompt.

> **Note (Windows):** If you encounter an execution policy error, run PowerShell as Administrator and execute:
>
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### Step 2: Navigate to the Source Directory

**macOS/Linux:**
```bash
cd python/src/app
```

**Windows (PowerShell):**
```powershell
cd python\src\app
```

### Step 3: Start the API Server with Uvicorn

Run the API server using Uvicorn:

```bash
uvicorn travel_agents_api:app --reload --host 0.0.0.0 --port 8000
```

Alternatively, you can run it directly with Python:

```bash
python travel_agents_api.py
```

### Expected Output

You should see:

```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### Verify the API

Open your browser and navigate to:
- **API Documentation**: **http://localhost:8000/docs**
- **Health Check**: **http://localhost:8000/health**

You should see the FastAPI Swagger UI with all available endpoints.

> **Keep this terminal open** - The API server needs to remain running for the frontend to work.

---

## Activity 4: Launch the Frontend

Now let's start the Angular frontend application.

### Step 1: Open a New Terminal

Open a new terminal window/tab (keep the API server running in the first terminal).

### Step 2: Navigate to the Frontend Directory

**macOS/Linux:**
```bash
cd ~/travel-multi-agent-workshop/01_exercises/frontend
```

**Windows (PowerShell):**
```powershell
cd ~\travel-multi-agent-workshop\01_exercises\frontend
```

### Step 3: Install Node Dependencies

Install the required npm packages:

```bash
npm install
```

This will install:

- Angular framework and CLI
- TypeScript
- RxJS
- Development dependencies

### Step 4: Start the Frontend Server

Start the Angular development server:

```bash
npm start
```

### Expected Output

You should see:

```
✔ Browser application bundle generation complete.

Initial Chunk Files   | Names         |  Size
main.js               | main          |  XX KB
polyfills.js          | polyfills     |  XX KB
styles.css            | styles        |  XX KB

                      | Initial Total |  XX KB

Build at: 2025-11-05T12:00:00.000Z - Hash: xxxxx
✔ Compiled successfully.
✔ Browser application bundle generation complete.

** Angular Live Development Server is listening on localhost:4200 **
```

### Access the Frontend

Open your browser and navigate to:

**http://localhost:4200**

---

## Activity 5: Verify Your Setup

Now that everything is running, let's verify the setup is correct.

### Step 1: Verify Data in Cosmos DB

Let's check that data was loaded correctly in Cosmos DB.

1. **Open the Azure Portal**: **https://portal.azure.com**
2. **Navigate to your Cosmos DB account**
3. **Go to Data Explorer**

Check the following containers:

#### Users Container

- **Container**: **Users**
- **Expected**: 4 user documents
- **Check for users**:
  - Tony Stark (**tony**)
  - Steve Rogers (**steve**)
  - Peter Parker (**peter**)
  - Bruce Banner (**bruce**)

#### Places Container

- **Container**: **Places**
- **Expected**: ~2,900 place documents
- **Categories**: Hotels, Restaurants, Activities
- **Sample cities**: Seattle, Tokyo, Paris, London, New York, etc.

Example place document structure:

```json
{
  "id": "hotel-seattle-001",
  "placeId": "hotel-seattle-001",
  "name": "Four Seasons Hotel Seattle",
  "type": "hotel",
  "city": "Seattle",
  "country": "USA",
  "description": "Luxury waterfront hotel...",
  "embedding": [0.123, -0.456, ...],
  ...
}
```

#### Memories Container

- **Container**: **Memories**
- **Expected**: 10 pre-existing memory documents
- **Users with memories**:
  - Tony Stark (5 memories)
  - Steve Rogers (5 memories)

Example memory document structure:

```json
{
  "id": "mem_tony_001",
  "memoryId": "mem_tony_001",
  "userId": "tony_stark",
  "tenantId": "default",
  "memoryText": "Tony prefers luxury hotels with modern architecture",
  "category": "hotel",
  "embedding": [0.789, -0.234, ...],
  "metadata": {
    "extractedFrom": "conversation",
    "confidence": "high"
  },
  ...
}
```

### Step 2: Explore the Frontend

Open the frontend at **http://localhost:4200**

#### Home Page

You should see:

- Welcome message
- Navigation menu with "Explore" and "Chat Assistant" options
- Brief introduction to the travel assistant

#### Explore Page

Click on "Explore" in the navigation menu. You should see:

- **City selector** dropdown
- **Category filters**: Hotels, Restaurants, Activities
- **Place cards** displaying places for the selected city

Try selecting different cities and categories to browse the available places:

- Select "Seattle" and "Hotels" to see Seattle hotels
- Select "Tokyo" and "Restaurants" to see Tokyo restaurants
- Select "Paris" and "Activities" to see Paris activities

#### Chat Assistant Page (Not Yet Functional)

Click on "Chat Assistant" in the navigation menu. You should see:

- Chat interface with message input
- **Expected behavior**: The chat assistant will respond with "Chat completion not implemented yet."
- **This is normal!** We haven't implemented the agents yet

> **Note:** In Module 01, you'll build your first agent to make the chat assistant functional.

---

## Success Criteria

Your setup is successful if you can verify:

✅ **Azure resources provisioned** via `azd up`  
✅ **Python virtual environment** (`.venv-travel`) **created** automatically  
✅ **Dependencies installed** without errors  
✅ **Environment variables configured** in `.env` files  
✅ **Database seeded successfully**:

- 4 users in the Users container
- ~2,900 places in the Places container
- 10 memories in the Memories container  
  ✅ **API server running** on http://localhost:8000  
  ✅ **API documentation accessible** at http://localhost:8000/docs  
  ✅ **Frontend running** on http://localhost:4200  
  ✅ **Explore page functional** and displays places correctly  
  ✅ **Chat Assistant page loads** (even though chat doesn't work yet)

---

## Troubleshooting

### Issue: azd up Fails

**Solution**: 

1. Verify you're in the correct directory (`01_exercises/infra`)
2. Verify you're logged in to the correct Azure tenant:
   ```bash
   azd auth login --tenant-id <TENANT_ID>
   ```

2. Confirm your subscription and tenant IDs are set:
   ```bash
   azd env get-values
   ```

3. Check you have appropriate permissions in the Azure subscription
4. If issues persist, try running `azd down` to clean up any partial deployments, then retry `azd up`

### Issue: Virtual Environment Not Activating

**Solution**: Ensure Python 3.11+ is installed:

**macOS/Linux:**
```bash
python3 --version
# or
python3.11 --version
```

**Windows:**
```powershell
python --version
```

If you encounter an execution policy error on Windows:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Issue: Dependencies Installation Fails

**Solution**: The `azd up` command should install dependencies automatically via the postprovision hook. If it failed:

1. Activate the virtual environment manually:
   
   **macOS/Linux:**
   ```bash
   source .venv-travel/bin/activate
   ```
   
   **Windows:**
   ```powershell
   .\.venv-travel\Scripts\Activate.ps1
   ```

2. Upgrade pip and reinstall:
   ```bash
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

### Issue: Data Seeding Failed

**Solution**: If the automatic seeding failed during `azd up`, run it manually:

1. Activate the virtual environment (see above)
2. Navigate to the python directory and run the seed script:

   **macOS/Linux:**
   ```bash
   cd python
   python data/seed_data.py
   cd ..
   ```
   
   **Windows:**
   ```powershell
   cd python
   python data\seed_data.py
   cd ..
   ```

### Issue: Authentication Error When Seeding Data

**Solution**: Verify your `.env` file configuration:

- Check `python/.env` exists and contains `COSMOSDB_ENDPOINT`
- On Windows, verify `COSMOS_KEY` is present
- Ensure the values match your Azure Cosmos DB account
- Try logging in to Azure again: `azd auth login`

### Issue: API Server Won't Start

**Solution**:

1. Check if port 8000 is already in use:
   
   **macOS/Linux:**
   ```bash
   lsof -i :8000
   ```
   
   **Windows:**
   ```powershell
   netstat -ano | findstr :8000
   ```

2. Kill the process or change the port

### Issue: Frontend Won't Start

**Solution**:

1. Ensure Node.js 18+ is installed:
   ```bash
   node --version
   ```

2. Clear npm cache and reinstall:
   
   **macOS/Linux:**
   ```bash
   npm cache clean --force
   rm -rf node_modules package-lock.json
   npm install
   ```
   
   **Windows:**
   ```powershell
   npm cache clean --force
   Remove-Item -Recurse -Force node_modules, package-lock.json
   npm install
   ```

### Issue: Explore Page Shows No Data

**Solution**:

1. Verify the API server is running on http://localhost:8000
2. Check browser console for errors (F12)
3. Verify the proxy configuration in `frontend/proxy.conf.json`:
   ```json
   {
     "/api": {
       "target": "http://localhost:8000",
       "secure": false
     }
   }
   ```

---

## Summary

Congratulations! You've successfully:

- Configured Azure authentication using Azure Developer CLI
- Provisioned Azure resources (Cosmos DB, Azure OpenAI, and supporting services)
- Verified resources in the Azure Portal
- Automatically created a Python virtual environment (`.venv-travel`)
- Installed dependencies and seeded Cosmos DB with users, places, and memories
- Started the API server using Uvicorn
- Launched the Angular frontend application
- Verified data in Cosmos DB containers
- Explored the frontend interface

With your environment set up and verified, you're ready to start building your first agent!

**Next**: [Module 01 - Creating Your First Agent](./Module-01.md)
