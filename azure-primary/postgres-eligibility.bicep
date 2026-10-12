targetScope = 'resourceGroup'

// Disposable PostgreSQL eligibility/connectivity test only. No application resources.
param location string = resourceGroup().location
param serverName string
param administratorLogin string = 'farmcrafttestadmin'
@secure()
param administratorLoginPassword string
@description('The single public IPv4 address of the test client. Never use 0.0.0.0.')
param allowedClientIp string

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: serverName
  location: location
  tags: { app: 'FarmCraft', purpose: 'disposable-postgres-eligibility-test' }
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorLoginPassword
    version: '16'
    storage: { storageSizeGB: 32, autoGrow: 'Disabled' }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
  }
}

resource firewall 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: server
  name: 'test-client-only'
  properties: { startIpAddress: allowedClientIp, endIpAddress: allowedClientIp }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: server
  name: 'farmcraft_test'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}

output fqdn string = server.properties.fullyQualifiedDomainName
output databaseName string = database.name
