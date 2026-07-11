param name string
param location string = resourceGroup().location
param tags object = {}
param environmentId string
param containerRegistryLoginServer string
param imageName string = ''
param targetPort int
param identityId string
param env array = []
param external bool = false
param minReplicas int = 0
param maxReplicas int = 1
param cpu string = '0.5'
param memory string = '1Gi'

// Use placeholder image for initial provisioning; azd deploy will update with the real image from ACR
var resolvedImage = !empty(imageName) ? '${containerRegistryLoginServer}/${imageName}' : 'mcr.microsoft.com/k8se/quickstart:latest'

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: external
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: !external
      }
      registries: [
        {
          server: containerRegistryLoginServer
          identity: identityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: name
          image: resolvedImage
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: env
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

output name string = containerApp.name
output fqdn string = containerApp.properties.configuration.ingress.fqdn
output uri string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
