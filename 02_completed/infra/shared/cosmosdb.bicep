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
param memoriesContainerName string = 'memories'
param turnsContainerName string = 'memories_turns'
param summariesContainerName string = 'memories_summaries'
param counterContainerName string = 'counter'
@description('Embedding dimensions for the memories container vector index. Must match the embedding model used by AgentMemoryToolkit (text-embedding-3-small = 1536).')
param memoriesEmbeddingDimensions int = 1536
@description('Default per-container autoscale max RU/s (autoscale floors at 10%). Dedicated per-container throughput avoids shared-throughput asymmetry trip wires.')
param containerMaxRU int = 1000
@description('Autoscale max RU/s for the Checkpoints container (storage + write hotspot).')
param checkpointsMaxRU int = 4000
@description('Autoscale max RU/s for the Places container (vector search).')
param placesMaxRU int = 2000
@description('TTL (seconds) for the Checkpoints container. Acts as the idle "resume-within" window for a conversation; older checkpoints (only needed for time-travel) expire. Default 7 days; lengthen for production. Set 0/-1 to disable.')
param checkpointsTtlSeconds int = 604800
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
        name: 'EnableNoSQLVectorSearch'
      }
      {
        name: 'EnableFabricNetworkAclBypass'
      }
    ]
    backupPolicy: {
      type: 'Continuous'
      continuousModeProperties: {
        tier: 'Continuous7Days'
      }
    }
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

// Custom Cosmos SQL RBAC role for Fabric mirroring (readMetadata + readAnalytics),
// pre-created for assignment to a Fabric workspace identity post-provision.
resource fabricMirroringRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions@2024-12-01-preview' = {
  parent: cosmosDb
  name: guid(cosmosDb.id, 'FabricMirroringRole')
  properties: {
    roleName: 'FabricMirroringRole'
    type: 'CustomRole'
    assignableScopes: [
      cosmosDb.id
    ]
    permissions: [
      {
        dataActions: [
          'Microsoft.DocumentDB/databaseAccounts/readMetadata'
          'Microsoft.DocumentDB/databaseAccounts/readAnalytics'
        ]
      }
    ]
  }
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
      options: {
      autoscaleSettings: {
        maxThroughput: containerMaxRU
      }
    }
  }
  tags: tags
}

// Container 2: Messages
// Partition Key: [/tenantId, /userId, /sessionId] (hierarchical)
// Vector search: /embedding (1536 dims, cosine, diskANN)
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
          {
            path: '/keywords'
            language: 'en-US'
          }
        ]
      }
    }
      options: {
      autoscaleSettings: {
        maxThroughput: containerMaxRU
      }
    }
  }
  tags: tags
}

// Container 3: Places
// Partition Key: /geoScopeId (simple)
// Vector search: /embedding (1536 dims, cosine, diskANN)
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
            dimensions: 1536
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
      options: {
      autoscaleSettings: {
        maxThroughput: placesMaxRU
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
      options: {
      autoscaleSettings: {
        maxThroughput: containerMaxRU
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
      options: {
      autoscaleSettings: {
        maxThroughput: containerMaxRU
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
      options: {
      autoscaleSettings: {
        maxThroughput: containerMaxRU
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
      options: {
      autoscaleSettings: {
        maxThroughput: containerMaxRU
      }
    }
  }
  tags: tags
}

// Container 8: Checkpoints (LangGraph)
// Partition Key: /session_id (simple)
// No vector search, no full-text search
resource cosmosContainerCheckpoints 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: checkpointsContainerName
  properties: {
    resource: {
      id: checkpointsContainerName
      // Bound checkpoint accumulation (LangGraph writes one per super-step, keeping
      // full history per thread). Only the latest per thread is needed to resume.
      defaultTtl: checkpointsTtlSeconds
      partitionKey: {
        paths: [
          '/session_id'
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
      options: {
      autoscaleSettings: {
        maxThroughput: checkpointsMaxRU
      }
    }
  }
  tags: tags
}


// Container 9: Memories (AgentMemoryToolkit)
// Partition Key: [/user_id, /thread_id] (hierarchical, MultiHash)
// Vector search: /embedding (diskANN), Full-text: /content (en-US)
// TTL enabled (per-doc opt-in), excluded paths match toolkit _container_policies
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
            path: '/"_etag"/?'
          }
          {
            path: '/embedding/*'
          }
          {
            path: '/source_memory_ids/*'
          }
          {
            path: '/supersedes_ids/*'
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
            language: 'en-US'
          }
        ]
        // Required by azure-cosmos-agent-memory synthesize_procedural — its
        // SELECT TOP 50 ... ORDER BY c.salience DESC, c.created_at ASC, c.id ASC
        // query needs a matching composite index (otherwise Cosmos returns a
        // BadRequest "order by query does not have a corresponding composite index").
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
            dimensions: memoriesEmbeddingDimensions
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
      options: {
      autoscaleSettings: {
        maxThroughput: containerMaxRU
      }
    }
  }
  tags: tags
}

// Container 10: Memories Turns (AgentMemoryToolkit turn documents)
// Partition Key: [/user_id, /thread_id] (hierarchical, MultiHash)
// TTL: 30 days (2592000 seconds) for automatic turn expiry
resource cosmosContainerMemoriesTurns 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: turnsContainerName
  properties: {
    resource: {
      id: turnsContainerName
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
            path: '/"_etag"/?'
          }
          {
            path: '/embedding/?'
          }
          {
            path: '/source_memory_ids/*'
          }
          {
            path: '/supersedes_ids/*'
          }
        ]
      }
    }
      options: {
      autoscaleSettings: {
        maxThroughput: containerMaxRU
      }
    }
  }
  tags: tags
}

// Container 11: Memories Summaries (AgentMemoryToolkit thread/user summaries)
// Partition Key: [/user_id, /thread_id] (hierarchical, MultiHash)
resource cosmosContainerMemoriesSummaries 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: summariesContainerName
  properties: {
    resource: {
      id: summariesContainerName
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
            path: '/"_etag"/?'
          }
          {
            path: '/embedding/?'
          }
          {
            path: '/source_memory_ids/*'
          }
          {
            path: '/supersedes_ids/*'
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
      options: {
      autoscaleSettings: {
        maxThroughput: containerMaxRU
      }
    }
  }
  tags: tags
}




// Container 12: Counter (azure-cosmos-agent-memory per-(user, thread) turn counts)
// Used by the toolkit's auto-trigger cadence (FACT_EXTRACTION_EVERY_N,
// DEDUP_EVERY_N, THREAD_SUMMARY_EVERY_N, USER_SUMMARY_EVERY_N).
// Partition Key: [/user_id, /thread_id] (hierarchical, MultiHash)
resource cosmosContainerCounter 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: counterContainerName
  properties: {
    resource: {
      id: counterContainerName
      partitionKey: {
        paths: [
          '/user_id'
          '/thread_id'
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
      options: {
      autoscaleSettings: {
        maxThroughput: containerMaxRU
      }
    }
  }
  tags: tags
}




// Outputs


output endpoint string = cosmosDb.properties.documentEndpoint
output name string = cosmosDb.name
output databaseName string = database.name
