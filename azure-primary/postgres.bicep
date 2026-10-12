targetScope = 'resourceGroup'

// New database only. Never point this at the live Neon database or existing event.
param location string = resourceGroup().location
param serverName string
param administratorLogin string
@secure()
param administratorLoginPassword string
param delegatedSubnetId string
param privateDnsZoneId string

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: serverName
  location: location
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorLoginPassword
    version: '16'
    storage: { storageSizeGB: 32, autoGrow: 'Disabled' }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: {
      delegatedSubnetResourceId: delegatedSubnetId
      privateDnsZoneArmResourceId: privateDnsZoneId
      publicNetworkAccess: 'Disabled'
    }
  }
}
resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  name: 'farmcraft'
  parent: server
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}
output fqdn string = server.properties.fullyQualifiedDomainName
