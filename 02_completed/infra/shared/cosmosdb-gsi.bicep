// Provisioned-throughput Cosmos DB account for GSI testing
// Mirrors the serverless account but with provisioned throughput and Global Secondary Indexes

param databaseName string
param sessionsContainerName string
param messagesContainerName string
param apiEventsContainerName string
param placesContainerName string
param tripsContainerName string
param usersContainerName string
param debugLogsContainerName string
param checkpointsContainerName string
param tripsByDestinationContainerName string
param memoriesContainerName string = 'memories'
param turnsContainerName string = 'memories_turns'
param summariesContainerName string = 'memories_summaries'
@description('Embedding dimensions for the memories container vector index. Must match the embedding model used by AgentMemoryToolkit (text-embedding-3-small = 1536).')
param memoriesEmbeddingDimensions int = 1536
param location string = resourceGroup().location
param name string
param tags object = {}

@description('Shared throughput for the database (RU/s). Set high for initial seeding, scale down after.')
param databaseThroughput int = 10000

@description('Dedicated throughput for the Trips container (RU/s). Set to 100000 to force 10 physical partitions.')
param tripsThroughput int = 100000

@description('Autoscale max throughput for the GSI container (RU/s).')
param gsiMaxThroughput int = 5000

// Cosmos DB Account — Provisioned throughput (no EnableServerless)
resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts@2024-12-01-preview' = {
  name: name
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    databaseAccountOfferType: 'Standard'
    disableLocalAuth: true
    enableMaterializedViews: true
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

// Database with shared throughput
resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-12-01-preview' = {
  parent: cosmosDb
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
    options: {
      throughput: databaseThroughput
    }
  }
  tags: tags
}

// Container 1: Sessions
resource cosmosContainerSessions 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: sessionsContainerName
  properties: {
    resource: {
      id: sessionsContainerName
      partitionKey: {
        paths: [ '/tenantId', '/userId', '/sessionId' ]
        kind: 'MultiHash'
        version: 2
      }
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

// Container 2: Messages (vector + full-text search)
resource cosmosContainerMessages 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: messagesContainerName
  properties: {
    resource: {
      id: messagesContainerName
      partitionKey: {
        paths: [ '/tenantId', '/userId', '/sessionId' ]
        kind: 'MultiHash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [ { path: '/*' } ]
        excludedPaths: [ { path: '/"_etag"/?' } ]
        vectorIndexes: [ { path: '/embedding', type: 'diskANN' } ]
        fullTextIndexes: [
          { path: '/content', language: 'en-us' }
          { path: '/keywords', language: 'en-us' }
        ]
      }
      vectorEmbeddingPolicy: {
        vectorEmbeddings: [ { path: '/embedding', dataType: 'float32', distanceFunction: 'cosine', dimensions: 1536 } ]
      }
      fullTextPolicy: {
        defaultLanguage: 'en-US'
        fullTextPaths: [
          { path: '/content', language: 'en-US' }
          { path: '/keywords', language: 'en-US' }
        ]
      }
    }
    options: {
      autoscaleSettings: {
        maxThroughput: 1000
      }
    }
  }
  tags: tags
}

// Container 3: Places (vector + full-text search)
resource cosmosContainerPlaces 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: placesContainerName
  properties: {
    resource: {
      id: placesContainerName
      partitionKey: {
        paths: [ '/geoScopeId' ]
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [ { path: '/*' } ]
        excludedPaths: [ { path: '/"_etag"/?' } ]
        vectorIndexes: [ { path: '/embedding', type: 'diskANN' } ]
        fullTextIndexes: [
          { path: '/name', language: 'en-us' }
          { path: '/description', language: 'en-us' }
          { path: '/tags', language: 'en-us' }
        ]
      }
      vectorEmbeddingPolicy: {
        vectorEmbeddings: [ { path: '/embedding', dataType: 'float32', distanceFunction: 'cosine', dimensions: 1536 } ]
      }
      fullTextPolicy: {
        defaultLanguage: 'en-US'
        fullTextPaths: [
          { path: '/name', language: 'en-US' }
          { path: '/description', language: 'en-US' }
          { path: '/tags', language: 'en-US' }
        ]
      }
    }
    options: {
      autoscaleSettings: {
        maxThroughput: 5000
      }
    }
  }
  tags: tags
}

// Container 4: Trips— dedicated throughput to force 10 physical partitions
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
        includedPaths: [ { path: '/*' } ]
        excludedPaths: [ { path: '/"_etag"/?' } ]
      }
    }
    options: {
      autoscaleSettings: {
        maxThroughput: tripsThroughput
      }
    }
  }
  tags: tags
}

// Container 4b: TripsByDestination — Global Secondary Index on Trips
resource cosmosContainerTripsByDestination 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: tripsByDestinationContainerName
  properties: {
    resource: {
      id: tripsByDestinationContainerName
      partitionKey: {
        paths: [ '/destination' ]
        kind: 'Hash'
        version: 2
      }
      materializedViewDefinition: {
        sourceCollectionId: tripsContainerName
        definition: 'SELECT c.id, c.tripId, c.userId, c.tenantId, c.destination, c.startDate, c.endDate, c.tripDuration, c.status, c.createdAt FROM c'
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [ { path: '/*' } ]
        excludedPaths: [ { path: '/"_etag"/?' } ]
      }
    }
    options: {
      autoscaleSettings: {
        maxThroughput: gsiMaxThroughput
      }
    }
  }
  dependsOn: [ cosmosContainerTrips ]
  tags: tags
}

// Container 5: Users
resource cosmosContainerUsers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: usersContainerName
  properties: {
    resource: {
      id: usersContainerName
      partitionKey: {
        paths: [ '/userId' ]
        kind: 'Hash'
        version: 2
      }
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

// Container 6: API Events
resource cosmosContainerApiEvents 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: apiEventsContainerName
  properties: {
    resource: {
      id: apiEventsContainerName
      partitionKey: {
        paths: [ '/tenantId', '/userId', '/sessionId' ]
        kind: 'MultiHash'
        version: 2
      }
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

// Container 7: Debug Logs
resource cosmosContainerDebugLogs 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: debugLogsContainerName
  properties: {
    resource: {
      id: debugLogsContainerName
      partitionKey: {
        paths: [ '/tenantId', '/userId', '/sessionId' ]
        kind: 'MultiHash'
        version: 2
      }
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

// Container 8: Checkpoints (LangGraph)
resource cosmosContainerCheckpoints 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: checkpointsContainerName
  properties: {
    resource: {
      id: checkpointsContainerName
      partitionKey: {
        paths: [ '/partition_key' ]
        kind: 'Hash'
        version: 2
      }
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

// Container 9: Memories (AgentMemoryToolkit)
// Partition Key: [/user_id, /thread_id] (hierarchical, MultiHash)
// Vector search: /embedding (diskANN), Full-text: /content (en-US)
resource cosmosContainerMemories 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: memoriesContainerName
  properties: {
    resource: {
      id: memoriesContainerName
      partitionKey: {
        paths: [ '/user_id', '/thread_id' ]
        kind: 'MultiHash'
        version: 2
      }
      defaultTtl: -1
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [ { path: '/*' } ]
        excludedPaths: [
          { path: '/"_etag"/?' }
          { path: '/embedding/*' }
          { path: '/source_memory_ids/*' }
          { path: '/supersedes_ids/*' }
        ]
        vectorIndexes: [
          { path: '/embedding', type: 'diskANN' }
        ]
        fullTextIndexes: [
          { path: '/content', language: 'en-US' }
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
          { path: '/content', language: 'en-US' }
        ]
      }
    }
  }
  tags: tags
}

// Container 10: Memories Turns (AgentMemoryToolkit turn documents)
// Partition Key: [/user_id, /thread_id] (hierarchical, MultiHash)
// TTL: 30 days (2592000 seconds)
resource cosmosContainerMemoriesTurns 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: turnsContainerName
  properties: {
    resource: {
      id: turnsContainerName
      partitionKey: {
        paths: [ '/user_id', '/thread_id' ]
        kind: 'MultiHash'
        version: 2
      }
      defaultTtl: 2592000
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [ { path: '/*' } ]
        excludedPaths: [
          { path: '/"_etag"/?' }
          { path: '/embedding/?' }
          { path: '/source_memory_ids/*' }
          { path: '/supersedes_ids/*' }
        ]
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
        paths: [ '/user_id', '/thread_id' ]
        kind: 'MultiHash'
        version: 2
      }
      defaultTtl: -1
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [ { path: '/*' } ]
        excludedPaths: [
          { path: '/"_etag"/?' }
          { path: '/embedding/?' }
          { path: '/source_memory_ids/*' }
          { path: '/supersedes_ids/*' }
        ]
        compositeIndexes: [
          [
            { path: '/user_id', order: 'ascending' }
            { path: '/thread_id', order: 'ascending' }
            { path: '/version', order: 'descending' }
          ]
        ]
      }
    }
  }
  tags: tags
}

// Outputs
output endpoint string = cosmosDb.properties.documentEndpoint
output name string = cosmosDb.name
output databaseName string = database.name
