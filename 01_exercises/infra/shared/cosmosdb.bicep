// Parameters
param databaseName string
param sessionsContainerName string
param messagesContainerName string
param summariesContainerName string
param memoriesContainerName string
param apiEventsContainerName string
param placesContainerName string
param tripsContainerName string
param usersContainerName string
param debugLogsContainerName string
param checkpointsContainerName string
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

// Container 3: Summaries
// Partition Key: [/tenantId, /userId, /sessionId] (hierarchical)
// Vector search: /embedding (1024 dims, cosine, diskANN)
// Full-text search: /text (en-us)
resource cosmosContainerSummaries 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: summariesContainerName
  properties: {
    resource: {
      id: summariesContainerName
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
            path: '/text'
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
            path: '/text'
            language: 'en-US'
          }
        ]
      }
    }
  }
  tags: tags
}

// Container 4: Memories
// Partition Key: [/tenantId, /userId, /memoryId] (hierarchical)
// Vector search: /embedding (1024 dims, cosine, diskANN)
// Full-text search: /text (en-us)
resource cosmosContainerMemories 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: memoriesContainerName
  properties: {
    resource: {
      id: memoriesContainerName
      partitionKey: {
        paths: [
          '/tenantId'
          '/userId'
          '/memoryId'
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
            path: '/text'
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
            path: '/text'
            language: 'en-US'
          }
        ]
      }
    }
  }
  tags: tags
}

// Container 5: Places
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

// Container 6: Trips
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

// Container 7: Users
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

// Container 8: API Events
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

// Container 9: Debug Logs
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

// Container 10: Checkpoints (LangGraph)
// Partition Key: /session_id (simple)
// No vector search, no full-text search
resource cosmosContainerCheckpoints 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = {
  parent: database
  name: checkpointsContainerName
  properties: {
    resource: {
      id: checkpointsContainerName
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
  }
  tags: tags
}


// Outputs


output endpoint string = cosmosDb.properties.documentEndpoint
output name string = cosmosDb.name
output databaseName string = database.name
