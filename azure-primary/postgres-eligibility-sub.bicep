targetScope = 'subscription'

param location string = 'koreacentral'
param resourceGroupName string
param serverName string
param allowedClientIp string
@secure()
param administratorLoginPassword string

resource isolatedGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: { app: 'FarmCraft', purpose: 'disposable-postgres-eligibility-test' }
}

module postgres './postgres-eligibility.bicep' = {
  name: 'postgres-eligibility'
  scope: isolatedGroup
  params: {
    location: location
    serverName: serverName
    allowedClientIp: allowedClientIp
    administratorLoginPassword: administratorLoginPassword
  }
}
