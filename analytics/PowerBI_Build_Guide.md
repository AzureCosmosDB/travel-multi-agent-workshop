# Power BI Report Build Guide

Step-by-step instructions for building the Travel Assistant Analytics report in Power BI Desktop using **Import mode**. This produces a portable `.pbit` template that anyone can open and connect to their own Fabric Lakehouse.

> **Reference screenshots** are in `analytics/media/` — use them as visual targets for each page.

---

## Prerequisites

- **Power BI Desktop** installed (latest version)
- The Spark notebook has been run and all 10 tables exist in your Fabric Lakehouse
- You have your Lakehouse **SQL Analytics Endpoint** URL (e.g., `xxxxx.datawarehouse.fabric.microsoft.com`)

To find the SQL Analytics Endpoint:
1. Open your Lakehouse in the Fabric portal
2. Click the **SQL Analytics Endpoint** dropdown (top-left, next to the Lakehouse name)
3. Copy the connection string

---

## Step 1: Create a New Report and Connect to Data

1. Open **Power BI Desktop**
2. Click **Get Data** → **SQL Server database**
3. Enter your Lakehouse SQL Analytics Endpoint URL as the **Server**
4. Leave **Database** blank (or enter your Lakehouse name)
5. Select **Import** as the Data Connectivity mode
6. Click **OK**
7. Authenticate with your **Microsoft account** (organizational account)
8. In the Navigator, expand to find your Lakehouse tables. Select all 10 tables:

| Table | Used On |
|-------|---------|
| `gold_user_memory_profile` | Pages 1 |
| `gold_memory_salience_analysis` | Pages 1, 2, 3 |
| `gold_destination_popularity` | Page 4 |
| `gold_place_inventory` | (not used — uniform data) |
| `gold_popular_places` | (not used — uniform data) |
| `gold_memory_trip_alignment` | Page 2 |
| `gold_memory_lifecycle` | Page 2 |
| `silver_memories_flat` | (supporting detail) |
| `silver_trips_days` | (supporting detail) |
| `silver_trip_activities` | Page 5 |

9. Click **Load** (not Transform Data)

---

## Step 2: Create a Parameter (Optional but Recommended)

This makes the report portable — users can change the server without editing Power Query.

1. Go to **Home** → **Transform data** (opens Power Query Editor)
2. In the Power Query Editor ribbon: **Home** → **Manage Parameters** → **New Parameter**
3. Set:
   - **Name:** `LakehouseSQLEndpoint`
   - **Type:** Text
   - **Current Value:** your SQL Analytics Endpoint URL
4. Click **OK**
5. In the left **Queries** pane, right-click any table → **Advanced Editor**
6. Find the server URL string (e.g., `"xxxxx.datawarehouse.fabric.microsoft.com"`) and replace it with `LakehouseSQLEndpoint`
7. Repeat for all 10 tables
8. Click **Close & Apply**

> If you skip this step, users can still change the connection via **Data source settings** after opening the file. The parameter just makes it cleaner.

---

## Step 3: Set Up the Report Theme

1. Use the default theme or pick a dark theme that works well for dashboards
2. Set the Canvas background to a dark color if desired (this matches the reference screenshots)

---

## Page 1: Memory Intelligence Overview

This page answers: **How much has the AI learned about its users?**

This is the executive summary of the AI's memory system. It shows the total volume and composition of knowledge the system has extracted from conversations — broken down by memory type, confidence level, and per-user distribution. Use it to understand at a glance how well the AI knows its users and how that knowledge is distributed.

### Tables Used
- `gold_user_memory_profile`
- `gold_memory_salience_analysis`

### Visuals to Build

#### 1a. KPI Cards (top row)
Create 4 **Card** visuals across the top:

| Card | Table | Measure |
|------|-------|---------|
| Total Memories | `gold_user_memory_profile` | Sum of `total_memories` |
| Number of Users | `gold_user_memory_profile` | Count of `userId` |
| Avg Salience | `gold_user_memory_profile` | Average of `avg_salience` |
| Active Memories | `gold_user_memory_profile` | Sum of `active_count` |

> **What this tells you:** At a glance, how much the AI has learned overall — total memories extracted from conversations, how many users it knows about, and how confident it is in what it knows (salience). A high active count relative to total means the AI's knowledge is current; a big gap means many memories have been superseded.

#### 1b. Memories by Type (Donut Chart)
- **Visual type:** Donut chart
- **Table:** `gold_user_memory_profile`
- **Legend:** Use the three count fields as separate values
- **Values:** Sum of `declarative_count`, Sum of `procedural_count`, Sum of `episodic_count`

> **What this tells you:** The overall composition of the AI's knowledge. Declarative memories are permanent facts (dietary restrictions, allergies). Procedural memories capture behavioral patterns (prefers late dinners, always walks). Episodic memories are trip-specific and expire after 90 days. A system dominated by declarative memories has strong, stable user profiles; a large episodic slice means lots of active trip planning.

#### 1c. Salience Distribution (Clustered Bar Chart)
- **Visual type:** Clustered bar chart
- **Table:** `gold_memory_salience_analysis`
- **Y-axis:** `salience_tier`
- **X-axis:** Count of `memoryId`
- **Legend:** `memoryType`

> **What this tells you:** How confident the AI is across all memories, broken down by type. High-salience memories (0.9–1.0) come from clear, explicit statements like "I'm allergic to peanuts." Lower-salience memories are inferred from context. The color breakdown by memory type reveals whether declarative facts tend to be higher confidence than episodic trip-specific preferences.

#### 1d. Memories per User by Type (Clustered Bar Chart)
- **Visual type:** Clustered bar chart
- **Table:** `gold_user_memory_profile`
- **Y-axis:** `name` (user name)
- **X-axis:** `declarative_count`, `procedural_count`, `episodic_count`
- **Legend:** The three count fields become the legend categories

> **What this tells you:** How well the AI knows each individual user, and the composition of that knowledge. Users with many declarative memories have clearly stated permanent preferences (vegan, allergic to peanuts). Users with more episodic memories have trip-specific requests that expire. A balanced mix across all three types means the AI captured facts, behavioral patterns, and in-the-moment requests. Users with few memories overall may need more conversations to build their profile.

---

## Page 2: Memory Health

This page answers: **How healthy is the AI's memory system?**

This page digs into the durability and lifecycle of the AI's knowledge. It shows whether memories are permanent or temporary, which users have the most stable vs. volatile preferences, and whether different memory types age differently. Use it to assess how well the memory system retains useful knowledge over time and how much conflict resolution the AI is performing.

### Tables Used
- `gold_memory_lifecycle`
- `gold_memory_salience_analysis`

### Visuals to Build

#### 2a. Memories by User Name and Memory Lifespan (Stacked Bar Chart)
- **Visual type:** Stacked bar chart
- **Table:** `gold_memory_lifecycle`
- **Y-axis:** `name` (user name)
- **X-axis:** Count of memories (Sum of `total`)
- **Legend:** `memory_lifespan`

> **What this tells you:** The balance between permanent and temporary knowledge per user. Users with mostly "Long-term (Permanent)" bars have well-established profiles built from dietary restrictions, accessibility needs, and behavioral patterns. Users heavy on "Short-term (90-day episodic)" are actively planning trips with temporary preferences that will expire. This reveals which users the AI knows deeply vs. which it only knows in the context of a current trip.

#### 2b. Memories by Memory Lifespan (Pie Chart)
- **Visual type:** Pie chart
- **Table:** `gold_memory_lifecycle`
- **Legend:** `memory_lifespan`
- **Values:** Count of memories (Sum of `total`)

> **What this tells you:** The system-wide split between permanent and temporary knowledge. A pie dominated by "Long-term (Permanent)" means the AI has built strong, lasting user profiles. A large "Short-term (90-day episodic)" slice means lots of trip-specific preferences are in play — these will expire and need refreshing on future trips. This is the aggregate view of what the stacked bar shows per user.

#### 2c. Active and Superseded by User (Stacked Bar Chart)
- **Visual type:** Stacked bar chart
- **Table:** `gold_memory_lifecycle`
- **Y-axis:** `name` (user name)
- **X-axis:** Sum of `active` and Sum of `superseded` (drag both to X-axis, they stack automatically)

> **What this tells you:** Which users change their minds the most. Users with large "superseded" segments had preference conflicts the AI detected and resolved (e.g., "I'm vegan" → "I eat seafood now"). Users with mostly "active" bars have stable, consistent preferences. This directly measures the AI's conflict resolution capability per user — if you ran the data enricher, you'll see superseded memories for the 6 users who had intentional preference conflicts added.

#### 2d. Memory Health by Memory Type (Stacked Bar Chart)
- **Visual type:** Stacked bar chart
- **Table:** `gold_memory_salience_analysis`
- **Y-axis:** `memoryType`
- **X-axis:** Count of `memoryId`
- **Legend:** `memory_health`

> **What this tells you:** Are declarative memories healthier than episodic ones? Declarative memories (permanent facts) should be mostly "Active" or "Superseded" since they don't expire. Episodic memories (trip-specific, 90-day TTL) are more likely to show "Aging" or "Stale" since they're temporary by design. A large "Superseded" segment in declarative memories means users frequently corrected their stated facts. This chart connects the memory type breakdown from Page 1 to the health story on this page.

---

## Page 3: User Preferences

This page answers: **What does the AI know about each user's preferences?**

This page explores the preference categories the AI has extracted from conversations — dietary needs, hotel style, activity types, budget, accessibility, and more. It shows the distribution of preferences, how they break down by memory type, and whether certain categories are healthier than others. Use it to understand which areas of user preference the AI focuses on most and how durable that knowledge is.

### Tables Used
- `gold_memory_salience_analysis`

### Visuals to Build

#### 3a. Preference Category Distribution (Donut Chart)
- **Visual type:** Donut chart
- **Table:** `gold_memory_salience_analysis`
- **Legend:** `facet_category`
- **Values:** Count of `memoryId`

> **What this tells you:** Which types of preferences the AI captures most from conversations. Is dining dominant? Are hotel preferences rare? A large "dietary" slice means users talk a lot about food restrictions. A small "accessibility" slice doesn't mean it's unimportant — it means fewer users mentioned it. This reveals the AI's attention distribution across preference categories.

#### 3b. Memory Type by Category (Stacked Bar Chart)
- **Visual type:** Stacked bar chart
- **Table:** `gold_memory_salience_analysis`
- **Y-axis:** `facet_category`
- **X-axis:** Count of `memoryId`
- **Legend:** `memoryType`

> **What this tells you:** How the AI classifies preferences within each category. Hotel preferences stored as "declarative" are permanent facts ("I need wheelchair access"). Hotel preferences stored as "episodic" are trip-specific ("I want a beach resort for this trip"). This shows whether each category is dominated by permanent knowledge or temporary trip-specific requests.

#### 3c. Memory Health by Category (Stacked Bar Chart)
- **Visual type:** Stacked bar chart
- **Table:** `gold_memory_salience_analysis`
- **Y-axis:** `facet_category`
- **X-axis:** Count of `memoryId`
- **Legend:** `memory_health`

> **What this tells you:** Which preference categories stay healthy vs. go stale or get superseded. For example, if dining preferences have a high "Superseded" count, it means users frequently change their food preferences and the AI detects the conflicts. If hotel preferences are mostly "Active", those preferences are stable and consistently used. Categories with many "Stale" memories may indicate over-extraction — the AI captured something it never used.

---

## Page 4: Trip Planning Insights

This page answers: **How is the AI planning trips?**

This page shifts from memory to action — it shows the trip planning process. It covers the lifecycle status of trips (planning, confirmed, completed), seasonal travel patterns, and how the AI structures each day's itinerary across time slots. Use it to understand the AI's trip planning behavior and whether it produces balanced, well-structured itineraries.

### Tables Used
- `gold_destination_popularity`
- `silver_trip_activities`

### Visuals to Build

#### 4a. Trip Status (Donut Chart)
- **Visual type:** Donut chart
- **Table:** `gold_destination_popularity`
- **Legend:** `status` (values: planning, confirmed, completed)
- **Values:** Sum of `trip_count`

> **What this tells you:** The trip lifecycle pipeline — how many trips are still being planned vs. confirmed vs. already completed. A large "planning" slice means users are actively working with the AI. A healthy mix of all three shows the system is being used end-to-end, not just for browsing.

#### 4b. Trips by Month (Donut Chart)
- **Visual type:** Donut chart
- **Table:** `gold_destination_popularity`
- **Legend:** `month_name`
- **Values:** Sum of `trip_count`

> **What this tells you:** Seasonal patterns in trip planning. Are users clustering trips in summer months, or is travel evenly distributed? This reveals whether the AI is handling seasonal demand and whether the generated personas have realistic travel timing.

#### 4c. Activity Slot Distribution (Donut Chart)
- **Visual type:** Donut chart
- **Table:** `silver_trip_activities`
- **Legend:** `slot` (morning, lunch, afternoon, dinner, accommodation)
- **Values:** Count of `tripId`

> **What this tells you:** How the AI structures each day's itinerary. Morning, afternoon, lunch, and dinner should be roughly equal (one per day). Accommodation is typically one per trip (not per day), so it should be a smaller slice. If any slot is underrepresented, it may indicate the AI is skipping that part of the itinerary for some trips. This is a direct measure of itinerary completeness.

---

## Page 5: Destination Intelligence

This page answers: **Where does the AI send people, and what do those trips look like?**

This page focuses on the destinations themselves — which cities are most popular, how long users stay, and how many individual recommendations the AI generates per city. Use it to understand the geographic spread of the AI's trip planning and which destinations get the richest itineraries.

### Tables Used
- `gold_destination_popularity`
- `silver_trip_activities`

### Visuals to Build

#### 5a. Top Destinations (Stacked Bar Chart)
- **Visual type:** Stacked bar chart
- **Table:** `gold_destination_popularity`
- **Y-axis:** `destination_city`
- **X-axis:** Sum of `trip_count`

> **What this tells you:** Which cities the AI plans trips for most frequently. Bangkok and Barcelona tend to dominate because multiple personas request them. Cities with only one trip reveal niche traveler interests. This reflects both user demand and the AI's ability to plan for diverse destinations.

#### 5b. Trip Duration by Destination (Bar Chart)
- **Visual type:** Bar chart
- **Table:** `gold_destination_popularity`
- **Y-axis:** `destination_city`
- **X-axis:** Average of `avg_duration_days`

> **What this tells you:** Which cities get longer trips vs. quick getaways. A city averaging 5 days suggests multi-day immersive itineraries, while a city averaging 2–3 days is a weekend city break. This pairs with the Top Destinations chart — one shows *where* people go, the other shows *how long* they stay. Differences in duration reveal how the AI tailors trip length to destination type.

#### 5c. Trip Recommendations by City (Stacked Bar Chart)
- **Visual type:** Stacked bar chart
- **Table:** `silver_trip_activities`
- **Y-axis:** `destination_city`
- **X-axis:** Count of `tripId`

> **What this tells you:** Which cities the AI fills with the most recommendations — hotels, restaurants, and activities. Unlike the Top Destinations chart (which counts trips), this counts every individual activity slot the AI filled. Cities with more multi-day trips naturally have more recommendations. A city with a high recommendation count relative to its trip count means the AI is planning dense, activity-packed itineraries there.

---

## Step 4: Final Formatting

1. **Page names:** Right-click each page tab and rename:
   - `Memory Intelligence`
   - `Memory Health`
   - `User Preferences`
   - `Trip Planning`
   - `Destination Intelligence`

2. **Page titles:** Add a text box at the top of each page with the page name

3. **Colors:** Apply consistent colors across pages:
   - Memory types: use 3 distinct colors for declarative/procedural/episodic
   - Place types: use 3 distinct colors for hotel/restaurant/activity
   - Trip status: use 3 distinct colors for planning/confirmed/completed

4. **Number formatting:** Right-click measures and format:
   - Percentages: 1 decimal place
   - Salience: 3 decimal places
   - Counts: whole numbers with comma separator

---

## Step 5: Save and Export

### Save as .pbix
**File** → **Save As** → `TravelAssistantReport.pbix`

### Export as .pbit Template (Recommended for distribution)
1. **File** → **Export** → **Power BI template (.pbit)**
2. Enter a description: "Travel Multi-Agent Analytics Report — connects to Fabric Lakehouse SQL endpoint"
3. Save as `TravelAssistantReport.pbit`

The `.pbit` file:
- Contains the report layout, visuals, and Power Query definitions
- Does **not** contain data (so it's small)
- Prompts users for the `LakehouseSQLEndpoint` parameter when opened (if you set up the parameter in Step 2)
- Users enter their own SQL Analytics Endpoint URL and the report loads their data

---

## Table Reference: All Column Schemas

### gold_user_memory_profile
| Column | Type | Description |
|--------|------|-------------|
| userId | string | User identifier |
| name | string | User display name |
| age | int | User age |
| gender | string | User gender |
| home_city | string | User's home city |
| home_country | string | User's home country |
| total_memories | long | Total memory count |
| declarative_count | long | Permanent fact memories |
| procedural_count | long | Behavioral pattern memories |
| episodic_count | long | Trip-specific memories (90d TTL) |
| superseded_count | long | Memories replaced by conflicts |
| active_count | long | Non-superseded memories |
| permanent_memory_count | long | Memories with no TTL |
| avg_salience | double | Average confidence score |
| max_salience | double | Highest salience |
| min_salience | double | Lowest salience |
| avg_days_since_last_used | double | Average days since recall |
| first_memory_date | timestamp | Earliest memory extraction |
| latest_memory_date | timestamp | Most recent memory extraction |
| active_pct | double | Percentage of active memories |
| conflict_rate_pct | double | Percentage superseded |

### gold_memory_salience_analysis
| Column | Type | Description |
|--------|------|-------------|
| memoryId | string | Memory identifier |
| userId | string | User identifier |
| userName | string | User display name |
| memoryType | string | declarative / procedural / episodic |
| facet_category | string | hotel / dining / activity / budget / accessibility |
| facet_preference | string | Extracted preference value |
| salience | double | Confidence score (0–1) |
| salience_tier | string | High / Medium-High / Medium / Low |
| is_superseded | boolean | Was replaced by newer memory |
| is_permanent | boolean | Has no TTL |
| ttl | long | Time-to-live in seconds |
| extracted_date | timestamp | When memory was created |
| last_used_date | timestamp | When memory was last recalled |
| days_since_extracted | int | Age of memory |
| days_since_last_used | int | Staleness |
| days_alive_before_superseded | int | Lifespan before replacement (null if active) |
| text | string | Memory text |
| memory_health | string | Active / Aging / Stale / Superseded |
| memory_lifespan | string | Long-term / Short-term (90-day) / Short-term (Custom) |
| was_recalled_after_extraction | boolean | Used after initial extraction |

### gold_destination_popularity
| Column | Type | Description |
|--------|------|-------------|
| destination_city | string | City name |
| destination_country | string | Country name |
| travel_month | int | Month number (1-12) |
| month_name | string | Month name |
| travel_year | int | Year |
| status | string | planning / confirmed / completed |
| trip_count | long | Number of trips |
| avg_duration_days | double | Average trip length |
| max_duration_days | long | Longest trip |
| min_duration_days | long | Shortest trip |
| unique_travelers | long | Distinct users |

### gold_place_inventory
| Column | Type | Description |
|--------|------|-------------|
| city_slug | string | City identifier slug |
| city_name | string | Human-readable city name |
| place_type | string | hotel / restaurant / activity |
| place_count | long | Number of places |

### gold_popular_places
| Column | Type | Description |
|--------|------|-------------|
| placeId | string | Place identifier |
| place_type | string | hotel / restaurant / activity |
| destination_city | string | City from trip |
| times_recommended | long | Total recommendation count |
| trips_featuring_place | long | Distinct trips with this place |
| unique_users_recommended_to | long | Distinct users |
| name | string | Place name |
| city_name | string | City name from Places table |

### gold_memory_trip_alignment
| Column | Type | Description |
|--------|------|-------------|
| userId | string | User identifier |
| userName | string | User display name |
| memory_category | string | Preference category (hotel/dining/activity/budget/accessibility) |
| mapped_place_type | string | Corresponding place type |
| memory_count_in_category | long | Memories in this category |
| avg_salience | double | Average salience in category |
| max_salience | double | Max salience in category |
| trip_activities_matching | long | Trip activities of matching type |
| unique_places_matching | long | Distinct places of matching type |
| trips_with_matching_type | long | Trips with matching type |
| has_alignment | boolean | Whether trips match preferences |

### gold_memory_lifecycle
| Column | Type | Description |
|--------|------|-------------|
| userId | string | User identifier |
| name | string | User display name |
| memoryType | string | declarative / procedural / episodic |
| memory_lifespan | string | Long-term / Short-term classification |
| total | long | Total memories |
| superseded | long | Superseded count |
| active | long | Active count |
| recalled | long | Recalled after extraction |
| never_recalled | long | Never recalled |
| avg_salience | double | Average salience |
| avg_age_days | double | Average memory age |
| avg_days_since_used | double | Average days since last recall |
| avg_days_before_superseded | double | Average lifespan before replacement |
| recall_rate_pct | double | Percentage recalled |
| supersession_rate_pct | double | Percentage superseded |

### silver_trip_activities
| Column | Type | Description |
|--------|------|-------------|
| tripId | string | Trip identifier |
| userId | string | User identifier |
| tenantId | string | Tenant identifier |
| destination | string | Full destination string |
| destination_city | string | City name |
| destination_country | string | Country name |
| startDate | string | Trip start date |
| endDate | string | Trip end date |
| tripDuration | long | Days |
| status | string | planning / confirmed / completed |
| createdAt | timestamp | Trip creation time |
| dayNumber | string | Day number in itinerary |
| dayDate | string | Date of this day |
| slot | string | morning / lunch / afternoon / dinner / accommodation |
| activity_name | string | Activity description |
| placeId | string | Place identifier |
| place_type | string | hotel / restaurant / activity |
| travel_month | int | Month number |
| travel_year | int | Year |
