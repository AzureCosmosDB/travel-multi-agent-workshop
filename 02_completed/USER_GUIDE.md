# Travel Assistant — User Guide

This guide explains how to use the completed Travel Assistant application: what it can do, how to talk to it effectively, and how its memory and agent system work.

---

## Table of Contents

1. [Overview](#overview)
2. [Starting the Application](#starting-the-application)
3. [Navigating the Frontend](#navigating-the-frontend)
4. [Talking to the Travel Assistant](#talking-to-the-travel-assistant)
5. [How the Agent System Works](#how-the-agent-system-works)
6. [Memory & Personalization](#memory--personalization)
7. [Trip Planning & Itineraries](#trip-planning--itineraries)
8. [Exploring Places Directly](#exploring-places-directly)
9. [Supported Destinations](#supported-destinations)
10. [Sample Users (Seed Data)](#sample-users-seed-data)
11. [Tips for Best Results](#tips-for-best-results)
12. [API Reference](#api-reference)

---

## Overview

The Travel Assistant is a multi-agent AI application that helps you plan personalized trips. It combines:

- **Specialized AI agents** that each handle a specific domain (hotels, dining, activities, itineraries)
- **Persistent memory** that learns your preferences across conversations
- **Semantic search** powered by Azure Cosmos DB vector search, so you can describe what you want in plain language rather than using filters
- **Azure OpenAI** for natural language understanding and response generation

The application has three running services:

| Service | Default Port | Purpose |
|---|---|---|
| **Frontend** (Angular) | `4200` | Web UI |
| **API Server** (FastAPI) | `8000` | Multi-agent backend |
| **MCP Server** | `8080` | Tool server for agents |

---

## Starting the Application

You need three terminals, each running one service.

### 1. Start the MCP Tool Server

```powershell
cd 02_completed\mcp_server
..\venv\Scripts\Activate.ps1
$env:PYTHONPATH="..\python"
python mcp_http_server.py
```

Wait until you see `Travel Assistant MCP server initialized` before starting the API server.

### 2. Start the API Server

```powershell
cd 02_completed\python
..\venv\Scripts\Activate.ps1
uvicorn src.app.travel_agents_api:app --reload --host 0.0.0.0 --port 8000
```

The API server will try to connect to the MCP server on startup with up to 5 retries, 10 seconds apart. Wait for `✅ Agents initialized successfully!` in the logs before using the application.

### 3. Start the Frontend

```powershell
cd 02_completed\frontend
npm install #only do first time
npm start
```

Open a browser and navigate to **http://localhost:4200**.

### Verify Everything Is Running

- **Frontend**: http://localhost:4200
- **API Health Check**: http://localhost:8000/health
- **API Documentation (Swagger)**: http://localhost:8000/docs
- **API Readiness**: http://localhost:8000/health/ready — returns `"status": "ready"` when agents are fully initialized

---

## Navigating the Frontend

The web application has five main sections accessible from the navigation bar:

### Home
The landing page presents a **trip planning form** where you can specify:
- **Destination** — type-ahead city search from the 49 supported cities
- **Dates** — travel start and end dates
- **Number of travelers**

Clicking "Start Planning" opens a chat session pre-loaded with your trip parameters.

### Chat
The primary interface for conversing with the travel assistant. Each conversation is a **session** that:
- Remembers context within the conversation
- Builds on your stored preferences from previous sessions
- Can be renamed, browsed, or deleted from the sidebar

### Explore
A browse interface for discovering places without the chat interface. You can:
- Select a city
- Choose a place type (Hotels, Restaurants, Attractions)
- Filter by price tier, dietary needs, and accessibility requirements
- Enter a free-text theme (e.g. "romantic waterfront") to run a semantic search

### Trips
Shows all itineraries that have been generated for your user. Each trip record stores:
- Destination and travel dates
- Number of travelers
- Day-by-day itinerary with places

### Profile
Displays your user account details, the Profile **User Summary** panel, and stored memories. From here you can review — and delete — memories the system has learned about you.

---

## Talking to the Travel Assistant

The assistant uses natural language, so you can write conversationally. You do not need to use menus or forms — just describe what you want.

### Example Conversations

**Starting a new trip:**
> "I want to plan a 5-day trip to Tokyo in April for two people."

**Searching for hotels:**
> "Find me a boutique hotel near the city center with a good spa."

**Searching for restaurants:**
> "Show me some great ramen spots that are open for dinner."

**Searching for activities:**
> "What are some good art museums I should visit?"

**Sharing preferences (the system will remember these):**
> "I'm vegetarian and I need wheelchair-accessible accommodations."

**Building an itinerary:**
> "Create a day-by-day itinerary using the hotel and restaurants we discussed."

**Asking for a recap:**
> "What restaurants did we find so far?"

### What the Orchestrator Handles Directly

Some requests are handled by the Orchestrator without routing to a specialist:

- Greetings and general questions about the assistant
- Clarifications about your preferences
- Requests that span multiple domains (the Orchestrator routes to multiple specialists)

---

## How the Agent System Works

The application has specialized agents that collaborate to plan your trip.

```
User message
     │
     ▼
┌─────────────┐
│ Orchestrator│  ◄── Entry point for all messages
│             │       Recalls memory, routes requests
└──────┬──────┘
       │
   routes to
       │
  ┌────┴─────┬──────────┬──────────────────┐
  ▼          ▼          ▼                  ▼
Hotel     Activity    Dining        Itinerary
Agent     Agent       Agent         Generator
  │          │          │                  │
  └──────────┴──────────┴───► synthesizes ─┘
                                           │
                                    Day-by-day plan

Memory auto-flush runs in the background every ~10 chat turns.
```

### Agent Responsibilities

| Agent | What it does | When it's invoked |
|---|---|---|
| **Orchestrator** | Receives all messages, recalls memory, routes to specialists | Always first |
| **Hotel Agent** | Searches accommodations and applies lodging preferences | "Find hotels", "Where should I stay?" |
| **Activity Agent** | Searches attractions and experiences and applies activity preferences | "Things to do", "Museums", "Tours" |
| **Dining Agent** | Searches restaurants and applies dining preferences | "Restaurants", "Where to eat", "Food" |
| **Itinerary Generator** | Creates day-by-day travel plans from gathered results | "Build an itinerary", "Plan my days" |

### Agent Routing Examples

| You say... | Routes to |
|---|---|
| "Find boutique hotels in Barcelona" | Hotel Agent |
| "What are the best tapas restaurants?" | Dining Agent |
| "Suggest museums and day trips" | Activity Agent |
| "Make me an itinerary with all of this" | Itinerary Generator |
| "What day trips did you suggest earlier?" | Orchestrator handles recap |

### Transfer Behaviour

Agents can hand off to each other. For example, after discovering hotels the Hotel Agent can transfer to the Itinerary Generator to incorporate those hotels into a day plan. You can also explicitly ask the assistant to do this:

> "Use the Ritz hotel we found and build a full itinerary around it."

---

## Memory & Personalization

The Travel Assistant uses the **`azure-cosmos-agent-memory`** PyPI package for memory (import path `azure.cosmos.agent_memory`). The SDK owns memory storage, extraction, summaries, user summaries, conflict handling, and the memory prompts.

All three Cosmos DB containers used by the SDK — `memories_turns` (raw turn log, TTL 30 days), `memories` (facts, episodics, procedurals — vector + full-text indexed at 1536 dims), and `memories_summaries` (thread and user summaries, composite-indexed by `(user_id, thread_id, version)`) — are provisioned ahead of time by Bicep (`infra/shared/cosmosdb.bicep`). The workshop's `seed_data.py` populates `memories_turns` and `memories` from the shipped JSON files; `memories_summaries` is left empty and filled by the runtime SDK as users chat. Memory records are partitioned by `(user_id, thread_id)`, where `thread_id` is the chat session ID. `tenantId` still scopes sessions, messages, trips, and places, but it is no longer part of memory records.

### Memory Types

| Type | Container | What it stores | How it is created |
|---|---|---|---|
| **turn** | `memories_turns` | Raw chat turns in a thread | Added as you chat |
| **fact** | `memories` | Durable preferences and trip facts | Produced by SDK flush |
| **episodic** | `memories` | Specific past experiences worth recalling | Produced by SDK flush |
| **procedural** | `memories` | Standing rules / how-to-handle-X guidance | Produced by SDK flush |
| **thread_summary** | `memories_summaries` | Thread-level conversation summaries | Produced by SDK flush |
| **user_summary** | `memories_summaries` | Cross-thread profile used for personalization | Produced/updated by SDK flush |

### How Preferences Are Captured

You do **not** need to say "remember that…". Chat turns are recorded as you talk, and every 10 chat turns a background auto-flush runs through `azure.cosmos.agent_memory` to extract facts, update summaries, and refresh the `user_summary`. For example:

- "I'm vegan" → can become a durable dietary fact
- "I usually prefer boutique hotels" → can become a lodging preference fact
- "We stayed at the Hotel Arts in Barcelona last year" → can become a trip history fact
- "I need a quiet room away from the street" → can become an accommodation requirement fact

### Conflict Detection

If new information conflicts with existing memory, the SDK's built-in conflict-resolution prompts handle the update path. Those prompts ship inside `azure.cosmos.agent_memory`; `preference_extraction.prompty`, `memory_conflict_resolution.prompty`, and `summarizer.prompty` have been removed from this repo.

### Viewing Your Memories

Your stored memories and Profile **User Summary** panel are visible in the **Profile** section of the frontend. Memories can be deleted individually if you want to reset a preference.

You can also query them via the API:
```
GET /users/{userId}/memories
GET /users/{userId}/summary
```

### Conversation Summarization

After every 10 chat turns, the API starts a background auto-flush task. This produces thread summaries, facts, and the cross-thread `user_summary` without interrupting the chat response.

---

## Trip Planning & Itineraries

### Creating an Itinerary via Chat

The recommended workflow is:

1. Tell the assistant your destination, dates, and number of travelers
2. Ask the Hotel Agent to find accommodations matching your needs
3. Ask the Activity Agent for things to do
4. Ask the Dining Agent for restaurant recommendations
5. Ask the Itinerary Generator to synthesize everything into a day-by-day plan

**Example:**
> "We've found the hotel and a few restaurants. Now create a 3-day itinerary that includes the Hotel Ritz on day 1, the Louvre and a Seine dinner cruise on day 2, and Montmartre with a Michelin dinner on day 3."

### Trip Status

Trips have a status field that moves through: `planning` → `booked` → `completed` → `cancelled`. This can be updated from the Trips page or via the API.

### Viewing Saved Trips

All generated itineraries appear in the **Trips** section of the frontend, organized by travel date. Each trip shows the destination, dates, travelers, and the full day-by-day plan.

---

## Exploring Places Directly

The **Explore** page lets you browse places without the chat interface, useful when you want to browse options visually.

### Search Modes

**With a theme (semantic search):**
Enter a descriptive theme like `"romantic candlelit"` or `"family-friendly outdoor"` and the system uses vector similarity to find matching places. This finds places by *meaning*, not just keyword matching.

**Without a theme (filter search):**
Browse by city, place type, price tier, dietary options, and accessibility requirements. Results are sorted by rating.

### Place Types

| Type | Examples |
|---|---|
| **Hotels** | Luxury resorts, boutique hotels, business hotels, bed & breakfasts |
| **Restaurants** | Fine dining, casual, street food, cafes, bars |
| **Attractions** | Museums, landmarks, tours, parks, entertainment venues |

### Price Tiers

| Tier | Description |
|---|---|
| `budget` | Economy options |
| `moderate` | Mid-range |
| `luxury` | Premium and high-end |

---

## Supported Destinations

The application has pre-loaded data for **49 cities** worldwide:

| Region | Cities |
|---|---|
| **Europe** | Amsterdam, Athens, Barcelona, Berlin, Brussels, Budapest, Copenhagen, Dublin, Edinburgh, Frankfurt, Glasgow, Istanbul, Lisbon, London, Madrid, Manchester, Milan, Oslo, Paris, Prague, Reykjavik, Rome, Stockholm, Vienna, Zurich |
| **Asia-Pacific** | Auckland, Bangkok, Beijing, Christchurch, Delhi, Hong Kong, Kuala Lumpur, Melbourne, Mumbai, Osaka, Seoul, Singapore, Sydney, Tokyo |
| **Americas** | Chicago, Los Angeles, Miami, New York, San Francisco, Seattle, Toronto, Vancouver |
| **Middle East** | Abu Dhabi, Dubai |

When specifying a destination to the assistant or in the Explore page, use the common city name (e.g. "Paris", "New York", "Tokyo"). The system normalizes these to the appropriate identifier.

---

## Sample Users (Seed Data)

The application is pre-seeded with four demo users, all under the `marvel` tenant. You can select any of these from the login screen or use them in API calls.

| User ID | Name | Tenant ID |
|---|---|---|
| `tony` | Tony Stark | `marvel` |
| `steve` | Steve Rogers | `marvel` |
| `bruce` | Bruce Banner | `marvel` |
| `peter` | Peter Parker | `marvel` |

Each user has an independent memory store, conversation history, and set of trips. You can also create new users via the API (`POST /users`).

---

## Tips for Best Results

### Be descriptive with preferences
The richer the description, the better the semantic search results:

> ✅ "Find a quiet boutique hotel near cultural sites, not too expensive"  
> vs  
> ❌ "Find a hotel"

### Share restrictions early
State dietary restrictions, accessibility needs, or budget limits at the start of a conversation. The toolkit flush turns these into reusable memory facts and the specialist agents can apply them in later recommendations:

> "Before we start, I should mention I'm celiac and need gluten-free dining options, and I travel with a wheelchair user."

### Use the Itinerary Generator last
First gather hotel, activity, and dining options by talking to each specialist. Then ask the Itinerary Generator to synthesize everything — this produces much richer day plans:

> "We've found the Four Seasons hotel, the Louvre, Musée d'Orsay, and two restaurants. Build a 3-day Paris itinerary from all of this."

### Let the memory system work for you
The more you use the assistant across sessions, the more personalized it becomes. Returning users automatically get recommendations filtered by their stored preferences without needing to re-specify them each time.

### Exploring before chatting
Use the **Explore** page to browse and get a feel for what's available in a city before starting a planning conversation. This helps you frame more specific requests.

### Session titles
Sessions are auto-named "New Conversation" by default. You can rename them for easy reference, or let the system generate a descriptive title by clicking the rename option — it uses AI to summarize the conversation.

---

## API Reference

The full interactive API documentation is available at **http://localhost:8000/docs** when the API server is running.

### Key Endpoint Groups

#### Health & Status
| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Basic liveness check |
| `GET` | `/health/ready` | Readiness check (agents initialized?) |
| `GET` | `/status` | Detailed service status |

#### Session Management
| Method | Path | Description |
|---|---|---|
| `POST` | `/tenant/{tenantId}/user/{userId}/sessions` | Create a new chat session |
| `GET` | `/tenant/{tenantId}/user/{userId}/sessions` | List all sessions for user |
| `GET` | `/tenant/{tenantId}/user/{userId}/sessions/{sessionId}/messages` | Get conversation history |
| `POST` | `/tenant/{tenantId}/user/{userId}/sessions/{sessionId}/rename` | Rename a session |
| `DELETE` | `/tenant/{tenantId}/user/{userId}/sessions/{sessionId}` | Delete a session |

#### Chat
| Method | Path | Description |
|---|---|---|
| `POST` | `/tenant/{tenantId}/user/{userId}/sessions/{sessionId}/completion` | Send a message, get agent response |
| `POST` | `/tenant/{tenantId}/user/{userId}/sessions/{sessionId}/summarize-name` | Auto-generate a session title |

#### Trip Management
| Method | Path | Description |
|---|---|---|
| `GET` | `/tenant/{tenantId}/user/{userId}/trips` | List all trips |
| `GET` | `/tenant/{tenantId}/user/{userId}/trips/{tripId}` | Get trip details |
| `PUT` | `/tenant/{tenantId}/user/{userId}/trips/{tripId}` | Update trip |
| `DELETE` | `/tenant/{tenantId}/user/{userId}/trips/{tripId}` | Delete trip |

#### Memory Management
| Method | Path | Description |
|---|---|---|
| `GET` | `/users/{userId}/memories` | Get stored memories (filterable by type/query) |
| `GET` | `/users/{userId}/summary` | Get the Profile User Summary |
| `DELETE` | `/users/{userId}/memories/{memoryId}` | Delete a specific memory (`session_id` identifies its thread) |

#### Places Discovery
| Method | Path | Description |
|---|---|---|
| `POST` | `/places/search` | Semantic vector search for places |
| `POST` | `/tenant/{tenantId}/places/filter` | Filter places by city, type, price, dietary, accessibility |
| `GET` | `/places/{placeId}` | Get details for a specific place |

#### Debug & Analytics
| Method | Path | Description |
|---|---|---|
| `GET` | `/tenant/{tenantId}/user/{userId}/sessions/{sessionId}/completiondetails/{debugLogId}` | Get token usage, model, agent routing details for a response |

### Chat Completion Request Format

The `/completion` endpoint accepts a plain text string as the request body (the user's message):

```
POST /tenant/marvel/user/tony/sessions/{sessionId}/completion
Content-Type: application/json

"Find me a luxury hotel in Paris with a spa"
```

The response is a list of messages representing the full conversation history for the session.

### Multi-Tenancy

Application data such as sessions, messages, trips, and places is scoped by `tenantId` and `userId`. Memory is the exception: `azure.cosmos.agent_memory` APIs use `/users/{userId}/...` paths, and memory records are partitioned by `(user_id, thread_id)` without `tenantId`.
