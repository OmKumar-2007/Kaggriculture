targetScope = 'subscription'

// Preview only until the separate Phase 4 provisioning approval is recorded.
param location string = 'koreacentral'
param resourceGroupName string = 'rg-farmcraft-azure-staging-20261012'
param serverName string = 'farmcraftstgpg20261012omk'
param administratorLogin string = 'farmcraft_admin'
@secure()
param administratorLoginPassword string

resource staging 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: {
    app: 'FarmCraft'
    purpose: 'isolated-azure-staging'
  }
}

module foundation './foundation.bicep' = {
  name: 'farmcraft-phase4-foundation'
  scope: staging
  params: { location: location }
}

module postgres './postgres.bicep' = {
  name: 'farmcraft-phase4-postgres'
  scope: staging
  params: {
    location: location
    serverName: serverName
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorLoginPassword
    delegatedSubnetId: foundation.outputs.postgresSubnetId
    privateDnsZoneId: foundation.outputs.privateDnsZoneId
  }
}
