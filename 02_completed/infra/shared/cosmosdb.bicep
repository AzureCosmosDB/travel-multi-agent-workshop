// Parameters
param databaseName string
param sessionsContainerName string
param messagesContainerName string
param apiEventsContainerName string
param placesContainerName string
param tripsContainerName string
param usersContainerName string
param debugLogsContainerName string
param checkpointsContainerName string
// azure.cosmos.agent_memory containers (must match the SDK's auto-create policy)
param memoriesContainerName string = 'memories'
param memoriesTurnsContainerName string = 'memories_turns'
param memoriesSummariesContainerName string = 'memories_summaries'
// SDK auto-trigger uses this container to track per-thread/per-user turn
// counts. Without it, THREAD_SUMMARY_EVERY_N / USER_SUMMARY_EVERY_N never fire.
param memoriesCounterContainerName string = 'counter'
param location string = resourceGroup().location
param name string
param tags object = {}

// Cosmos DB Account
resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: name
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    databaseAccountOfferType: 'Standard'
    disableLocalAuth: true
    locations: [
      {
        failoverPriority: 0
        isZoneRedundant: false
        locationName: location
      }
    ]
    capabilities: [
      {
        name: 'EnableServerless'
      }
      {
        name: 'EnableNoSQLVectorSearch'
      }
    ]
  }
  tags: tags
}

// Database
resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-12-01-preview' = {
  parent: cosmosDb
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
  tags: tags
}

// Container 1: Sessions
// Partition Key: [/tenantId, /userId, /sessionId] (hierarchical)
// No vector search, no full-text search
resource cosmosContainerSessions 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: sessionsContainerName
  properties: {
    resource: {
      id: sessionsContainerName
      partitionKey: {
        paths: [
          '/tenantId'
          '/userId'
          '/sessionId'
        ]
        kind: 'MultiHash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/"_etag"/?'
          }
        ]
      }
    }
  }
  tags: tags
}

// Container 2: Messages
// Partition Key: [/tenantId, /userId, /sessionId] (hierarchical)
// Vector search: /embedding (1024 dims, cosine, diskANN)
// Full-text search: /content, /keywords (en-us)
resource cosmosContainerMessages 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: messagesContainerName
  properties: {
    resource: {
      id: messagesContainerName
      partitionKey: {
        paths: [
          '/tenantId'
          '/userId'
          '/sessionId'
        ]
        kind: 'MultiHash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/"_etag"/?'
          }
        ]
        vectorIndexes: [
          {
            path: '/embedding'
            type: 'diskANN'
          }
        ]
        fullTextIndexes: [
          {
            path: '/content'
            language: 'en-us'
          }
          {
            path: '/keywords'
            language: 'en-us'
          }
        ]
      }
      vectorEmbeddingPolicy: {
        vectorEmbeddings: [
          {
            path: '/embedding'
            dataType: 'float32'
            distanceFunction: 'cosine'
            dimensions: 1024
          }
        ]
      }
      fullTextPolicy: {
        defaultLanguage: 'en-US'
        fullTextPaths: [
          {
            path: '/content'
            language: 'en-US'
          }
          {
            path: '/keywords'
            language: 'en-US'
          }
        ]
      }
    }
  }
  tags: tags
}

// Container 3: Places
// Partition Key: /geoScopeId (simple)
// Vector search: /embedding (1024 dims, cosine, diskANN)
// Full-text search: /name, /description, /tags (en-us)
resource cosmosContainerPlaces 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: placesContainerName
  properties: {
    resource: {
      id: placesContainerName
      partitionKey: {
        paths: [
          '/geoScopeId'
        ]
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/"_etag"/?'
          }
        ]
        vectorIndexes: [
          {
            path: '/embedding'
            type: 'diskANN'
          }
        ]
        fullTextIndexes: [
          {
            path: '/name'
            language: 'en-us'
          }
          {
            path: '/description'
            language: 'en-us'
          }
          {
            path: '/tags'
            language: 'en-us'
          }
        ]
      }
      vectorEmbeddingPolicy: {
        vectorEmbeddings: [
          {
            path: '/embedding'
            dataType: 'float32'
            distanceFunction: 'cosine'
            dimensions: 1024
          }
        ]
      }
      fullTextPolicy: {
        defaultLanguage: 'en-US'
        fullTextPaths: [
          {
            path: '/name'
            language: 'en-US'
          }
          {
            path: '/description'
            language: 'en-US'
          }
          {
            path: '/tags'
            language: 'en-US'
          }
        ]
      }
    }
  }
  tags: tags
}

// Container 4: Trips
// Partition Key: [/tenantId, /userId, /tripId] (hierarchical)
// No vector search, no full-text search
resource cosmosContainerTrips 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: tripsContainerName
  properties: {
    resource: {
      id: tripsContainerName
      partitionKey: {
        paths: [
          '/tenantId'
          '/userId'
          '/tripId'
        ]
        kind: 'MultiHash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/"_etag"/?'
          }
        ]
      }
    }
  }
  tags: tags
}

// Container 5: Users
// Partition Key: /userId (simple)
// No vector search, no full-text search
resource cosmosContainerUsers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: usersContainerName
  properties: {
    resource: {
      id: usersContainerName
      partitionKey: {
        paths: [
          '/userId'
        ]
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/"_etag"/?'
          }
        ]
      }
    }
  }
  tags: tags
}

// Container 6: API Events
// Partition Key: [/tenantId, /userId, /sessionId] (hierarchical) - UPDATED
// No vector search, no full-text search
resource cosmosContainerApiEvents 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: apiEventsContainerName
  properties: {
    resource: {
      id: apiEventsContainerName
      partitionKey: {
        paths: [
          '/tenantId'
          '/userId'
          '/sessionId'
        ]
        kind: 'MultiHash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/"_etag"/?'
          }
        ]
      }
    }
  }
  tags: tags
}

// Container 7: Debug Logs
// Partition Key: [/tenantId, /userId, /sessionId] (hierarchical)
// No vector search, no full-text search
resource cosmosContainerDebugLogs 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: debugLogsContainerName
  properties: {
    resource: {
      id: debugLogsContainerName
      partitionKey: {
        paths: [
          '/tenantId'
          '/userId'
          '/sessionId'
        ]
        kind: 'MultiHash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/"_etag"/?'
          }
        ]
      }
    }
  }
  tags: tags
}

// Container 8: Checkpoints (LangGraph)
// Partition Key: /partition_key (required by langchain-azure-cosmosdb)
// No vector search, no full-text search
resource cosmosContainerCheckpoints 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: checkpointsContainerName
  properties: {
    resource: {
      id: checkpointsContainerName
      partitionKey: {
        paths: [
          '/partition_key'
        ]
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/"_etag"/?'
          }
        ]
      }
    }
  }
  tags: tags
}

// Container 9: memories_turns
// Partition Key: [/user_id, /thread_id] (hierarchical)
// Default TTL: 30 days (DEFAULT_TTL_BY_TYPE['turn'] in the SDK)
// No vector, no full-text — raw turn log used to feed extraction.
resource cosmosContainerMemoriesTurns 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: memoriesTurnsContainerName
  properties: {
    resource: {
      id: memoriesTurnsContainerName
      partitionKey: {
        paths: [
          '/user_id'
          '/thread_id'
        ]
        kind: 'MultiHash'
        version: 2
      }
      defaultTtl: 2592000
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/embedding/?'
          }
          {
            path: '/source_memory_ids/*'
          }
          {
            path: '/supersedes_ids/*'
          }
          {
            path: '/"_etag"/?'
          }
        ]
      }
    }
  }
  tags: tags
}

// Container 10: memories (facts, episodics, procedurals)
// Partition Key: [/user_id, /thread_id] (hierarchical)
// Vector: /embedding (1536-dim cosine diskANN float32 — text-embedding-3-small)
// Full-text: /content (en-US)
// Composite index (salience DESC, created_at ASC, id ASC) — required for the
//   SDK's procedural-synthesis ORDER BY.
resource cosmosContainerMemories 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: memoriesContainerName
  properties: {
    resource: {
      id: memoriesContainerName
      partitionKey: {
        paths: [
          '/user_id'
          '/thread_id'
        ]
        kind: 'MultiHash'
        version: 2
      }
      defaultTtl: -1
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/embedding/*'
          }
          {
            path: '/source_memory_ids/*'
          }
          {
            path: '/supersedes_ids/*'
          }
          {
            path: '/"_etag"/?'
          }
        ]
        vectorIndexes: [
          {
            path: '/embedding'
            type: 'diskANN'
          }
        ]
        fullTextIndexes: [
          {
            path: '/content'
          }
        ]
        compositeIndexes: [
          [
            {
              path: '/salience'
              order: 'descending'
            }
            {
              path: '/created_at'
              order: 'ascending'
            }
            {
              path: '/id'
              order: 'ascending'
            }
          ]
        ]
      }
      vectorEmbeddingPolicy: {
        vectorEmbeddings: [
          {
            path: '/embedding'
            dataType: 'float32'
            distanceFunction: 'cosine'
            dimensions: 1536
          }
        ]
      }
      fullTextPolicy: {
        defaultLanguage: 'en-US'
        fullTextPaths: [
          {
            path: '/content'
            language: 'en-US'
          }
        ]
      }
    }
  }
  tags: tags
}

// Container 11: memories_summaries
// Partition Key: [/user_id, /thread_id] (hierarchical)
// No vector, no full-text — the SDK doesn't index summaries that way.
// Composite index (user_id ASC, thread_id ASC, version DESC) for "latest summary" lookups.
resource cosmosContainerMemoriesSummaries 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: memoriesSummariesContainerName
  properties: {
    resource: {
      id: memoriesSummariesContainerName
      partitionKey: {
        paths: [
          '/user_id'
          '/thread_id'
        ]
        kind: 'MultiHash'
        version: 2
      }
      defaultTtl: -1
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/embedding/?'
          }
          {
            path: '/source_memory_ids/*'
          }
          {
            path: '/supersedes_ids/*'
          }
          {
            path: '/"_etag"/?'
          }
        ]
        compositeIndexes: [
          [
            {
              path: '/user_id'
              order: 'ascending'
            }
            {
              path: '/thread_id'
              order: 'ascending'
            }
            {
              path: '/version'
              order: 'descending'
            }
          ]
        ]
      }
    }
  }
  tags: tags
}


// Container 12: counter (SDK auto-trigger state)
// Partition Key: [/user_id, /thread_id] (hierarchical — matches SDK counter doc shape)
// No TTL, no special indexing. The SDK reads/writes counters per
// (user_id, thread_id) so it can fire FACT_EXTRACTION_EVERY_N,
// THREAD_SUMMARY_EVERY_N, USER_SUMMARY_EVERY_N, and DEDUP_EVERY_N at the
// right turn boundaries. User-scoped counters use thread_id="__counters__".
resource cosmosContainerMemoriesCounter 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: memoriesCounterContainerName
  properties: {
    resource: {
      id: memoriesCounterContainerName
      partitionKey: {
        paths: [
          '/user_id'
          '/thread_id'
        ]
        kind: 'MultiHash'
        version: 2
      }
      defaultTtl: -1
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [ { path: '/*' } ]
        excludedPaths: [ { path: '/"_etag"/?' } ]
      }
    }
  }
  tags: tags
}


// Outputs


output endpoint string = cosmosDb.properties.documentEndpoint
output name string = cosmosDb.name
output databaseName string = database.name
