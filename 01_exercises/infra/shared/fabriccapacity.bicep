metadata description = 'Creates a Microsoft Fabric capacity (smallest F-SKU by default) for the analytics/optimization Fabric pipeline.'

@description('Globally-unique capacity name (lowercase letters + digits only, 3-63 chars).')
param name string

@description('Region for the Fabric capacity. Fabric capacities are only available in a subset of regions and may be subject to internal placement restrictions, so this is a separate override from the app resource location.')
param location string

@description('Fabric capacity SKU. F2 is the smallest; the reverse-ETL Spark notebook can burst via Spark Autoscale Billing so the base capacity stays small.')
param skuName string = 'F2'

@description('Capacity administrators (UPNs / emails). The deploying user is added so they can manage the capacity and the workspace.')
param adminMembers array

param tags object = {}

resource capacity 'Microsoft.Fabric/capacities@2023-11-01' = {
  name: name
  location: location
  sku: {
    name: skuName
    tier: 'Fabric'
  }
  properties: {
    administration: {
      members: adminMembers
    }
  }
  tags: tags
}

output name string = capacity.name
output id string = capacity.id
output location string = capacity.location
