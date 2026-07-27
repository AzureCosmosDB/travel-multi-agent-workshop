targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment that can be used as part of naming resource convention')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

@description('Id of the user or app to assign application roles')
param principalId string

@description('Id of the service principal to assign application roles (optional - if not provided, SP roles will be skipped)')
param servicePrincipalId string = ''

@description('Owner tag for resource tagging')
param owner string = 'defaultuser@example.com'

@description('Override the resource group name. Defaults to rg-<environmentName>.')
param resourceGroupName string = ''

@description('Deploy a provisioned-throughput Cosmos DB account with GSI instead of serverless')
param deployGsi bool = false

@description('Deploy the optional analytics/optimization Cosmos containers (Modules 07/08). Default true; set false for a leaner base workshop.')
param deployAnalytics bool = true

@description('Deploy the app as hosted Azure Container Apps (API + MCP + frontend). Default FALSE for the exercises — run the app locally during the workshop. Set true (DEPLOY_HOSTED_APP=true) + uncomment the services in azure.yaml to deploy a hosted instance.')
param deployHostedApp bool = false

@description('Region for the Fabric capacity (deployed when deployAnalytics=true). Fabric capacities are region-restricted; override with FABRIC_CAPACITY_LOCATION when the app region is not an allowed Fabric region. Defaults to the app location.')
param fabricCapacityLocation string = ''

@description('Fabric capacity SKU (deployed when deployAnalytics=true). F2 is the smallest; the reverse-ETL Spark notebook bursts via Spark Autoscale Billing.')
param fabricCapacitySku string = 'F2'

var tags = {
  'azd-env-name': environmentName
  'owner': owner
}

var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))

resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: !empty(resourceGroupName) ? resourceGroupName : 'rg-${environmentName}'
  location: location
  tags: tags
}

// Deploy Managed Identity
module managedIdentity './shared/managedidentity.bicep' = {
  name: 'managed-identity'
  params: {
    identityName: '${abbrs.managedIdentityUserAssignedIdentities}${resourceToken}'
    location: location
    tags: tags
  }
  scope: rg
}

// Deploy Azure Cosmos DB (serverless — default)
module cosmos './shared/cosmosdb.bicep' = if (!deployGsi) {
  name: 'cosmos'
  params: {
    name: '${abbrs.documentDBDatabaseAccounts}${resourceToken}'
    location: location
    tags: tags
    databaseName: 'TravelAssistant'
    sessionsContainerName: 'Sessions'
    messagesContainerName: 'Messages'
    apiEventsContainerName: 'ApiEvents'
    placesContainerName: 'Places'
    tripsContainerName: 'Trips'
    usersContainerName: 'Users'
    debugLogsContainerName: 'Debug'
    checkpointsContainerName: 'Checkpoints'
    optimizationPoliciesContainerName: 'OptimizationPolicies'
    optimizationTurnsContainerName: 'OptimizationTurns'
    optimizationInsightsContainerName: 'OptimizationInsights'
    deployAnalytics: deployAnalytics
  }
  scope: rg
}

// Deploy Azure Cosmos DB (provisioned with GSI — optional)
module cosmosGsi './shared/cosmosdb-gsi.bicep' = if (deployGsi) {
  name: 'cosmos-gsi'
  params: {
    name: '${abbrs.documentDBDatabaseAccounts}${resourceToken}'
    location: location
    tags: tags
    databaseName: 'TravelAssistant'
    sessionsContainerName: 'Sessions'
    messagesContainerName: 'Messages'
    apiEventsContainerName: 'ApiEvents'
    placesContainerName: 'Places'
    tripsContainerName: 'Trips'
    tripsByDestinationContainerName: 'TripsByDestination'
    usersContainerName: 'Users'
    debugLogsContainerName: 'Debug'
    checkpointsContainerName: 'Checkpoints'
    memoriesContainerName: 'memories'
    turnsContainerName: 'memories_turns'
    summariesContainerName: 'memories_summaries'
  }
  scope: rg
}

// Deploy OpenAI
module openAi './shared/openai.bicep' = {
  name: 'foundry-account'
  params: {
    name: 'foundry-${resourceToken}'
    location: location
    tags: tags
    sku: 'S0'
  }
  scope: rg
}

//Deploy OpenAI Deployments
var deployments = [
  {
    name: 'gpt-5.1'
    skuCapacity: 30
	skuName: 'GlobalStandard'
    modelName: 'gpt-5.1'
    modelVersion: '2025-11-13'
  }
  {
    name: 'text-embedding-3-small'
    skuCapacity: 5
	skuName: 'GlobalStandard'
    modelName: 'text-embedding-3-small'
    modelVersion: '1'
  }
  {
    name: 'gpt-5-nano'
    skuCapacity: 30
    skuName: 'GlobalStandard'
    modelName: 'gpt-5-nano'
    modelVersion: '2025-08-07'
  }
  {
    name: 'gpt-5-mini'
    skuCapacity: 30
    skuName: 'GlobalStandard'
    modelName: 'gpt-5-mini'
    modelVersion: '2025-08-07'
  }
]

@batchSize(1)
module openAiModelDeployments './shared/modeldeployment.bicep' = [
  for (deployment, _) in deployments: {
    name: 'foundry-model-deployment-${deployment.name}'
    params: {
      name: deployment.name
      parentAccountName: openAi.outputs.name
      skuName: deployment.skuName
      skuCapacity: deployment.skuCapacity
      modelName: deployment.modelName
      modelVersion: deployment.modelVersion
      modelFormat: 'OpenAI'
    }
	scope: rg
  }
]

//Assign Roles to Managed Identities
module AssignRoles './shared/assignroles.bicep' = if (!deployGsi) {
  name: 'AssignRoles'
  params: {
    cosmosDbAccountName: cosmos.outputs.name
    openAIName: openAi.outputs.name
    identityName: managedIdentity.outputs.name
	  userPrincipalId: !empty(principalId) ? principalId : null
	servicePrincipalId: !empty(servicePrincipalId) ? servicePrincipalId : ''
  }
  scope: rg
}


module AssignRolesGsi './shared/assignroles.bicep' = if (deployGsi) {
  name: 'AssignRolesGsi'
  params: {
    cosmosDbAccountName: cosmosGsi.outputs.name
    openAIName: openAi.outputs.name
    identityName: managedIdentity.outputs.name
    userPrincipalId: !empty(principalId) ? principalId : null
    servicePrincipalId: !empty(servicePrincipalId) ? servicePrincipalId : ''
  }
  scope: rg
}


// ============================================================================
// Optional hosted app (Azure Container Apps) — gated by deployHostedApp (default false)
// ============================================================================
var cosmosEndpoint = deployGsi ? cosmosGsi.outputs.endpoint : cosmos.outputs.endpoint

var appBaseEnv = [
  { name: 'COSMOSDB_ENDPOINT', value: cosmosEndpoint }
  { name: 'COSMOSDB_DATABASE_NAME', value: 'TravelAssistant' }
  { name: 'AZURE_OPENAI_ENDPOINT', value: openAi.outputs.endpoint }
  { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: 'text-embedding-3-small' }
  { name: 'AZURE_OPENAI_DEPLOYMENT', value: 'gpt-5.1' }
  { name: 'AZURE_OPENAI_API_VERSION', value: '2025-04-01-preview' }
  { name: 'AZURE_CLIENT_ID', value: managedIdentity.outputs.clientId }
  { name: 'MCP_AUTH_SECRET_KEY', value: 'travel-mcp-server-jwt-secret-for-local-development' }
  { name: 'MCP_AUTH_TOKEN', value: 'travel-server-dev-token-2024' }
]

module logAnalytics './shared/loganalytics.bicep' = if (deployHostedApp) {
  name: 'log-analytics'
  params: {
    name: '${abbrs.operationalInsightsWorkspaces}${resourceToken}'
    location: location
    tags: tags
  }
  scope: rg
}

module containerRegistry './shared/containerregistry.bicep' = if (deployHostedApp) {
  name: 'container-registry'
  params: {
    name: '${abbrs.containerRegistryRegistries}${resourceToken}'
    location: location
    tags: tags
    identityPrincipalId: managedIdentity.outputs.principalId
  }
  scope: rg
}

module containerAppsEnvironment './shared/containerappenvironment.bicep' = if (deployHostedApp) {
  name: 'container-apps-environment'
  params: {
    name: '${abbrs.appManagedEnvironments}${resourceToken}'
    location: location
    tags: tags
    logAnalyticsWorkspaceName: logAnalytics.outputs.name
  }
  scope: rg
}

module mcpServerApp './shared/containerapp.bicep' = if (deployHostedApp) {
  name: 'mcp-server-app'
  params: {
    name: '${abbrs.appContainerApps}mcp-${resourceToken}'
    location: location
    tags: union(tags, { 'azd-service-name': 'mcp-server' })
    environmentId: containerAppsEnvironment.outputs.id
    containerRegistryLoginServer: containerRegistry.outputs.loginServer
    targetPort: 8080
    identityId: managedIdentity.outputs.id
    external: false
    minReplicas: 1
    maxReplicas: 3
    cpu: '1'
    memory: '2Gi'
    env: concat(appBaseEnv, [
      { name: 'PORT', value: '8080' }
    ])
  }
  scope: rg
}

module apiApp './shared/containerapp.bicep' = if (deployHostedApp) {
  name: 'api-app'
  params: {
    name: '${abbrs.appContainerApps}api-${resourceToken}'
    location: location
    tags: union(tags, { 'azd-service-name': 'api' })
    environmentId: containerAppsEnvironment.outputs.id
    containerRegistryLoginServer: containerRegistry.outputs.loginServer
    targetPort: 8000
    identityId: managedIdentity.outputs.id
    external: false
    minReplicas: 1
    maxReplicas: 3
    cpu: '1'
    memory: '2Gi'
    env: concat(appBaseEnv, [
      { name: 'MCP_SERVER_BASE_URL', value: 'http://${mcpServerApp.outputs.fqdn}' }
      { name: 'PORT', value: '8000' }
    ])
  }
  scope: rg
}

module frontendApp './shared/containerapp.bicep' = if (deployHostedApp) {
  name: 'frontend-app'
  params: {
    name: '${abbrs.appContainerApps}web-${resourceToken}'
    location: location
    tags: union(tags, { 'azd-service-name': 'frontend' })
    environmentId: containerAppsEnvironment.outputs.id
    containerRegistryLoginServer: containerRegistry.outputs.loginServer
    targetPort: 80
    identityId: managedIdentity.outputs.id
    external: true
    minReplicas: 1
    maxReplicas: 3
    cpu: '0.25'
    memory: '0.5Gi'
    env: [
      { name: 'API_BASE_URL', value: 'http://${apiApp.outputs.fqdn}' }
    ]
  }
  scope: rg
}


// Fabric capacity for the analytics/optimization pipeline (gated by deployAnalytics).
var fabricCapacityLocationResolved = empty(fabricCapacityLocation) ? location : fabricCapacityLocation
module fabricCapacity './shared/fabriccapacity.bicep' = if (deployAnalytics) {
  name: 'fabric-capacity'
  params: {
    name: 'fab${resourceToken}'
    location: fabricCapacityLocationResolved
    skuName: fabricCapacitySku
    adminMembers: [ owner ]
    tags: tags
  }
  scope: rg
}


// Outputs
output RG_NAME string = 'rg-${environmentName}'
output COSMOSDB_ENDPOINT string = deployGsi ? cosmosGsi.outputs.endpoint : cosmos.outputs.endpoint
output DEPLOY_GSI string = deployGsi ? 'true' : 'false'
output AZURE_OPENAI_ENDPOINT string = openAi.outputs.endpoint
output AZURE_OPENAI_COMPLETIONSDEPLOYMENTID string = openAiModelDeployments[0].outputs.name
output AZURE_OPENAI_EMBEDDINGDEPLOYMENTID string = openAiModelDeployments[1].outputs.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = deployHostedApp ? containerRegistry.outputs.loginServer : ''
output AZURE_CONTAINER_REGISTRY_NAME string = deployHostedApp ? containerRegistry.outputs.name : ''
output FRONTEND_URI string = deployHostedApp ? frontendApp.outputs.uri : ''
output FABRIC_CAPACITY_NAME string = deployAnalytics ? fabricCapacity.outputs.name : ''
output FABRIC_CAPACITY_ID string = deployAnalytics ? fabricCapacity.outputs.id : ''
output MANAGED_IDENTITY_PRINCIPAL_ID string = managedIdentity.outputs.principalId
