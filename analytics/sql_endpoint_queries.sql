-- =============================================================================
-- Travel Multi-Agent Analytics — SQL Endpoint Queries
-- =============================================================================
-- Run these against the Fabric SQL Analytics Endpoint for your mirrored
-- Cosmos DB database (TravelAssistantDatabase) or against the Lakehouse gold tables.
--
-- These queries work on flat properties and are suitable for quick Power BI
-- DirectQuery connections to the SQL Endpoint.
-- =============================================================================


-- =============================================================================
-- SECTION 1: MEMORY ANALYTICS
-- Best run directly against the mirrored Memories table via SQL Endpoint.
-- =============================================================================

-- 1.1 Memory type distribution (Page 1 — donut chart)
SELECT
    memoryType,
    COUNT(*)                                            AS memory_count,
    ROUND(AVG(CAST(salience AS FLOAT)), 3)              AS avg_salience,
    SUM(CASE WHEN supersededBy IS NOT NULL THEN 1 ELSE 0 END) AS superseded_count,
    SUM(CASE WHEN supersededBy IS     NULL THEN 1 ELSE 0 END) AS active_count
FROM Memories
GROUP BY memoryType
ORDER BY memory_count DESC;


-- 1.2 Salience score distribution by tier (Page 1 — bar/histogram)
SELECT
    CASE
        WHEN CAST(salience AS FLOAT) >= 0.9 THEN '4. High (0.9–1.0)'
        WHEN CAST(salience AS FLOAT) >= 0.7 THEN '3. Medium-High (0.7–0.9)'
        WHEN CAST(salience AS FLOAT) >= 0.5 THEN '2. Medium (0.5–0.7)'
        ELSE                                     '1. Low (<0.5)'
    END                         AS salience_tier,
    memoryType,
    COUNT(*)                    AS memory_count,
    ROUND(AVG(CAST(salience AS FLOAT)), 3) AS avg_salience
FROM Memories
WHERE supersededBy IS NULL   -- only active memories
GROUP BY
    CASE
        WHEN CAST(salience AS FLOAT) >= 0.9 THEN '4. High (0.9–1.0)'
        WHEN CAST(salience AS FLOAT) >= 0.7 THEN '3. Medium-High (0.7–0.9)'
        WHEN CAST(salience AS FLOAT) >= 0.5 THEN '2. Medium (0.5–0.7)'
        ELSE                                     '1. Low (<0.5)'
    END,
    memoryType
ORDER BY salience_tier, memoryType;


-- 1.3 Per-user memory count and average salience (Page 2 — bar chart)
SELECT
    m.userId,
    u.name                                                          AS userName,
    COUNT(*)                                                        AS total_memories,
    SUM(CASE WHEN m.memoryType = 'declarative' THEN 1 ELSE 0 END)  AS declarative,
    SUM(CASE WHEN m.memoryType = 'procedural'  THEN 1 ELSE 0 END)  AS procedural,
    SUM(CASE WHEN m.memoryType = 'episodic'    THEN 1 ELSE 0 END)  AS episodic,
    SUM(CASE WHEN m.supersededBy IS NOT NULL   THEN 1 ELSE 0 END)  AS superseded,
    ROUND(AVG(CAST(m.salience AS FLOAT)), 3)                        AS avg_salience,
    ROUND(
        100.0 * SUM(CASE WHEN m.supersededBy IS NOT NULL THEN 1 ELSE 0 END)
              / COUNT(*), 1
    )                                                               AS conflict_rate_pct
FROM Memories m
LEFT JOIN Users u ON m.userId = u.userId
GROUP BY m.userId, u.name
ORDER BY total_memories DESC;


-- 1.4 Active vs superseded memories over time — monthly extraction trend
--     (Page 1 — line chart: learning rate)
SELECT
    FORMAT(TRY_CAST(extractedAt AS DATETIME2), 'yyyy-MM') AS extraction_month,
    COUNT(*)                                               AS memories_extracted,
    SUM(CASE WHEN supersededBy IS     NULL THEN 1 ELSE 0 END) AS ultimately_active,
    SUM(CASE WHEN supersededBy IS NOT NULL THEN 1 ELSE 0 END) AS ultimately_superseded
FROM Memories
WHERE extractedAt IS NOT NULL
GROUP BY FORMAT(TRY_CAST(extractedAt AS DATETIME2), 'yyyy-MM')
ORDER BY extraction_month;


-- 1.5 Memory permanence breakdown (Page 5 — short vs long-term)
SELECT
    memoryType,
    CASE
        WHEN CAST(ttl AS BIGINT) = -1        THEN 'Long-term (Permanent)'
        WHEN CAST(ttl AS BIGINT) = 7776000   THEN 'Short-term (90-day episodic)'
        WHEN ttl IS NULL                     THEN 'No TTL set'
        ELSE 'Short-term (Custom TTL)'
    END                         AS memory_lifespan,
    COUNT(*)                    AS count,
    ROUND(AVG(CAST(salience AS FLOAT)), 3) AS avg_salience
FROM Memories
GROUP BY
    memoryType,
    CASE
        WHEN CAST(ttl AS BIGINT) = -1        THEN 'Long-term (Permanent)'
        WHEN CAST(ttl AS BIGINT) = 7776000   THEN 'Short-term (90-day episodic)'
        WHEN ttl IS NULL                     THEN 'No TTL set'
        ELSE 'Short-term (Custom TTL)'
    END
ORDER BY memoryType, memory_lifespan;


-- 1.6 Top preference keywords (Page 2 — word cloud or bar)
--     Note: keywords is a JSON array; for SQL Endpoint use OPENJSON or STRING_SPLIT
--     depending on how Fabric mirroring surfaces it. Adjust as needed.
SELECT TOP 30
    keyword_value,
    COUNT(*) AS occurrences
FROM Memories
CROSS APPLY OPENJSON(
    CASE
        WHEN ISJSON(CAST(keywords AS NVARCHAR(MAX))) = 1
        THEN CAST(keywords AS NVARCHAR(MAX))
        ELSE '[]'
    END
) WITH (keyword_value NVARCHAR(255) '$')
WHERE keyword_value IS NOT NULL
  AND LEN(keyword_value) > 2
GROUP BY keyword_value
ORDER BY occurrences DESC;


-- =============================================================================
-- SECTION 2: USER ANALYTICS
-- =============================================================================

-- 2.1 User demographics (Page 2 — supporting table)
SELECT
    userId,
    name,
    age,
    gender,
    JSON_VALUE(address, '$.city')    AS home_city,
    JSON_VALUE(address, '$.state')   AS home_state,
    JSON_VALUE(address, '$.country') AS home_country,
    TRY_CAST(createdAt AS DATETIME2) AS createdAt
FROM Users
ORDER BY name;


-- =============================================================================
-- SECTION 3: TRIP ANALYTICS (flat fields only — nested days require Spark)
-- =============================================================================

-- 3.1 Trip status breakdown (Page 3 — pie chart)
SELECT
    status,
    COUNT(*)                    AS trip_count,
    ROUND(AVG(CAST(tripDuration AS FLOAT)), 1) AS avg_duration_days,
    MIN(CAST(tripDuration AS INT))             AS min_duration_days,
    MAX(CAST(tripDuration AS INT))             AS max_duration_days
FROM Trips
GROUP BY status
ORDER BY trip_count DESC;


-- 3.2 Top destinations (Page 3 — bar chart)
SELECT TOP 20
    destination,
    COUNT(*)                    AS trip_count,
    ROUND(AVG(CAST(tripDuration AS FLOAT)), 1) AS avg_duration_days,
    SUM(CASE WHEN status = 'confirmed' THEN 1 ELSE 0 END) AS confirmed,
    SUM(CASE WHEN status = 'planning'  THEN 1 ELSE 0 END) AS planning
FROM Trips
GROUP BY destination
ORDER BY trip_count DESC;


-- 3.3 Trip duration distribution (Page 3 — bar/histogram)
SELECT
    CAST(tripDuration AS INT)   AS duration_days,
    COUNT(*)                    AS trip_count,
    status
FROM Trips
GROUP BY CAST(tripDuration AS INT), status
ORDER BY duration_days;


-- 3.4 Trips by departure month (Page 3 — heatmap/line)
SELECT
    MONTH(TRY_CAST(startDate AS DATE))  AS travel_month,
    YEAR(TRY_CAST(startDate  AS DATE))  AS travel_year,
    DATENAME(MONTH, TRY_CAST(startDate AS DATE)) AS month_name,
    COUNT(*)                            AS trip_count,
    status
FROM Trips
WHERE startDate IS NOT NULL
GROUP BY
    MONTH(TRY_CAST(startDate AS DATE)),
    YEAR(TRY_CAST(startDate  AS DATE)),
    DATENAME(MONTH, TRY_CAST(startDate AS DATE)),
    status
ORDER BY travel_year, travel_month;


-- 3.5 User × destination matrix (Page 4 — matrix visual)
SELECT
    t.userId,
    u.name                      AS userName,
    t.destination,
    COUNT(*)                    AS trips,
    SUM(CAST(t.tripDuration AS INT)) AS total_days_traveling
FROM Trips t
LEFT JOIN Users u ON t.userId = u.userId
GROUP BY t.userId, u.name, t.destination
ORDER BY u.name, trips DESC;


-- =============================================================================
-- SECTION 4: PLACES ANALYTICS (flat fields — geoScopeId is city slug)
-- =============================================================================

-- 4.1 Place inventory by city and type (Page 4 — stacked bar)
--     Place type inferred from id prefix
SELECT
    geoScopeId                          AS city_slug,
    REPLACE(INITCAP(geoScopeId), '_', ' ') AS city_name,  -- may vary by SQL dialect
    CASE
        WHEN id LIKE 'hotel_%'      THEN 'hotel'
        WHEN id LIKE 'restaurant_%' THEN 'restaurant'
        WHEN id LIKE 'activity_%'   THEN 'activity'
        ELSE 'unknown'
    END                                 AS place_type,
    COUNT(*)                            AS place_count
FROM Places
GROUP BY
    geoScopeId,
    CASE
        WHEN id LIKE 'hotel_%'      THEN 'hotel'
        WHEN id LIKE 'restaurant_%' THEN 'restaurant'
        WHEN id LIKE 'activity_%'   THEN 'activity'
        ELSE 'unknown'
    END
ORDER BY city_slug, place_type;


-- 4.2 Total places per city (for treemap — Page 4)
SELECT
    geoScopeId                          AS city_slug,
    COUNT(*)                            AS total_places,
    SUM(CASE WHEN id LIKE 'hotel_%'      THEN 1 ELSE 0 END) AS hotels,
    SUM(CASE WHEN id LIKE 'restaurant_%' THEN 1 ELSE 0 END) AS restaurants,
    SUM(CASE WHEN id LIKE 'activity_%'   THEN 1 ELSE 0 END) AS activities
FROM Places
GROUP BY geoScopeId
ORDER BY total_places DESC;


-- =============================================================================
-- SECTION 5: CROSS-CONTAINER SUMMARY QUERIES
-- Use these against the gold_ tables written by the Spark notebook
-- =============================================================================

-- 5.1 Memory health overview (Page 5 — KPI cards)
SELECT
    COUNT(*)                AS total_memories,
    SUM(CASE WHEN is_superseded = 1 THEN 1 ELSE 0 END)  AS superseded,
    SUM(CASE WHEN is_superseded = 0 THEN 1 ELSE 0 END)  AS active,
    ROUND(100.0 *
        SUM(CASE WHEN is_superseded = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS supersession_rate_pct,
    ROUND(AVG(CAST(salience AS FLOAT)), 3)               AS avg_salience,
    SUM(CASE WHEN is_permanent = 1 THEN 1 ELSE 0 END)   AS long_term_permanent,
    SUM(CASE WHEN is_permanent = 0 THEN 1 ELSE 0 END)   AS short_term_with_ttl,
    ROUND(100.0 *
        SUM(CASE WHEN was_recalled_after_extraction = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS recall_rate_pct
FROM gold_memory_salience_analysis;  -- from Lakehouse


-- 5.2 Preference category breakdown across all users (Page 2 — bar)
SELECT
    facet_category,
    COUNT(*)                     AS memory_count,
    ROUND(AVG(CAST(salience AS FLOAT)), 3) AS avg_salience,
    SUM(CASE WHEN is_superseded = 1 THEN 1 ELSE 0 END) AS conflict_count
FROM silver_memories_flat         -- from Lakehouse
WHERE facet_category IS NOT NULL
GROUP BY facet_category
ORDER BY memory_count DESC;


-- 5.3 Memory-Trip alignment summary (Page 5 — alignment gauge)
SELECT
    userName,
    memory_category,
    mapped_place_type,
    memory_count_in_category,
    ROUND(avg_salience, 3)       AS avg_salience,
    trip_activities_matching,
    has_alignment
FROM gold_memory_trip_alignment   -- from Lakehouse
ORDER BY userName, memory_category;
