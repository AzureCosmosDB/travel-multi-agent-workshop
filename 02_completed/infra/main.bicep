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

@description('Deploy a provisioned-throughput Cosmos DB account with GSI instead of serverless')
param deployGsi bool = false

@description('Override the resource group name. Defaults to rg-<environmentName>.')
param resourceGroupName string = ''

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
    memoriesContainerName: 'memories'
    turnsContainerName: 'memories_turns'
    summariesContainerName: 'memories_summaries'
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
  name: 'openai-account'
  params: {
    name: '${abbrs.openAiAccounts}${resourceToken}'
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
    skuCapacity: 50
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
    name: 'openai-model-deployment-${deployment.name}'
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


// Outputs
output RG_NAME string = 'rg-${environmentName}'
output COSMOSDB_ENDPOINT string = deployGsi ? cosmosGsi.outputs.endpoint : cosmos.outputs.endpoint
output AZURE_OPENAI_ENDPOINT string = openAi.outputs.endpoint
output AZURE_OPENAI_COMPLETIONSDEPLOYMENTID string = openAiModelDeployments[0].outputs.name
output AZURE_OPENAI_EMBEDDINGDEPLOYMENTID string = openAiModelDeployments[1].outputs.name
output DEPLOY_GSI string = deployGsi ? 'true' : 'false'
