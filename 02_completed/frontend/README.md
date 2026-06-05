# Cosmos Voyager - Travel Assistant Frontend

Angular-based frontend for the Travel Assistant Multi-Agent System.

## Features

- 🏠 **Home**: Hero section with trending themes and trip planning
- 🗺️ **Explore**: Browse hotels, restaurants, and attractions with filters
- 💬 **Chat**: Real-time agent conversation with specialized travel concierges
- 👤 **Profile**: Review the User Summary panel and manage memories
- ✈️ **Trips**: View and manage itineraries

## Prerequisites

- Node.js 18+ and npm
- Angular CLI 18+
- Backend API running on `http://localhost:8000`

## Installation

```bash
# Install dependencies
npm install

# Install Angular CLI globally (if not already installed)
npm install -g @angular/cli
```

## Development

```bash
# Start development server with API proxy
npm start

# The app will be available at http://localhost:4200
# API requests to /api/* will be proxied to http://localhost:8000
```

## Build

```bash
# Build for production
npm run build

# Output will be in dist/cosmos-voyager
```

## Project Structure

```
src/
├── app/
│   ├── components/
│   │   ├── home/              # Home page with hero section
│   │   ├── explore/           # Places exploration with filters
│   │   ├── profile/           # User profile and memories
│   │   ├── trips/             # Trip itineraries
│   │   └── shared/            # Reusable components (chat, cards, etc.)
│   ├── models/                # TypeScript interfaces
│   ├── services/              # API services
│   ├── app.component.*        # Root component
│   ├── app.config.ts          # App configuration
│   └── app.routes.ts          # Routing configuration
├── styles.css                 # Global styles (Tailwind)
└── index.html                 # HTML entry point
```

## Architecture

### API Integration

The frontend communicates with the FastAPI backend via the `TravelApiService`:

- **Thread Management**: Create, list, and manage conversation threads
- **Chat Completion**: Send messages and receive agent responses
- **Places Search**: Search for hotels, restaurants, and attractions
- **Trips**: Create and manage itineraries
- **Memories**: Retrieve user memories and the Profile User Summary via toolkit-backed endpoints

### Memory layer

Memory is provided by the **`azure-cosmos-agent-memory`** PyPI package (import path `azure.cosmos.agent_memory`) in the backend. The SDK uses three Cosmos DB containers — `memories_turns` (raw turns), `memories` (facts, episodics, procedurals), and `memories_summaries` (thread and user summaries) — all provisioned by Bicep at deploy time. Every 10 chat turns a background auto-flush produces a thread summary, extracted facts/episodics, and refreshes the `user_summary`. Memory records are partitioned by `(user_id, thread_id)`, not `tenantId`, and the memory prompts ship inside the SDK instead of this repo.

### State Management

Uses RxJS `BehaviorSubject` for reactive state management:

- `currentThread$`: Currently active conversation thread
- `messages$`: Messages in current thread
- `threads$`: List of all user threads

### Components

#### Core Components

- **AppComponent**: Root component with top bar and navigation
- **HomeComponent**: Landing page with hero section
- **ExploreComponent**: Places grid with filters and map view
- **ProfileComponent**: User preferences and past highlights
- **TripsComponent**: Itinerary list and day-by-day views

#### Shared Components

- **ChatDrawerComponent**: Slide-out chat interface
- **PlaceCardComponent**: Place display card with actions
- **MessageComponent**: Chat message bubble
- **ChipComponent**: Tag/filter chip
- **ToastComponent**: Notification toast

## API Endpoints Used

```
GET    /api/tenant/{tenantId}/user/{userId}/threads
POST   /api/tenant/{tenantId}/user/{userId}/threads
POST   /api/tenant/{tenantId}/user/{userId}/threads/{threadId}/completion
GET    /api/tenant/{tenantId}/user/{userId}/places/search
GET    /api/tenant/{tenantId}/user/{userId}/trips
GET    /api/users/{userId}/memories
GET    /api/users/{userId}/summary
```

## Environment Configuration

The app uses a proxy configuration (`proxy.conf.json`) to route `/api/*` requests to the backend:

```json
{
  "/api": {
    "target": "http://localhost:8000",
    "secure": false,
    "changeOrigin": true
  }
}
```

## Styling

Uses Tailwind CSS with custom Cosmos theme colors:

- **Primary**: `#0078D4` (Azure Blue)
- **Accent**: `#00BCF2` (Light Blue)

Configure in `tailwind.config.js`.

## Development Workflow

1. **Start Backend** (Port 8000):

   ```bash
   cd ../python
   python -m src.app.services.mcp_http_server &
   uvicorn src.app.travel_agents_api:app --reload --host 0.0.0.0 --port 8000
   ```

2. **Start Frontend** (Port 4200):

   ```bash
   cd frontend
   npm start
   ```

3. **Open Browser**:
   - Frontend: http://localhost:4200
   - Backend API Docs: http://localhost:8000/docs

## Testing

```bash
# Run unit tests
npm test

# Run tests with coverage
npm run test:coverage
```

## TODO

- [ ] Implement Home component with hero section
- [ ] Implement Explore component with places grid
- [ ] Implement Chat drawer component
- [ ] Implement Profile component
- [ ] Implement Trips component
- [ ] Add map view for places
- [ ] Add image support for places
- [ ] Implement authentication
- [ ] Add loading states and error handling
- [ ] Add responsive mobile design
- [ ] Add animations and transitions

## Related Documentation

- [Backend API Development Notes](../python/DEVELOPMENT_NOTES.md)
- [Angular Documentation](https://angular.io/docs)
- [Tailwind CSS](https://tailwindcss.com/docs)

---

**Created**: October 2025  
**Framework**: Angular 18 + Tailwind CSS  
**Backend**: FastAPI + LangGraph Multi-Agent System
