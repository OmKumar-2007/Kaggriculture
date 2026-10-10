targetScope = 'resourceGroup'

@description('Allowed Azure deployment region. UAE North is the verified first candidate.')
param location string = 'uaenorth'

@description('Globally unique PostgreSQL server name.')
param serverName string = 'farmcraft-pg-stg-2026'

@description('Database administrator login. Create a less-privileged application role after provisioning.')
param administratorLogin string = 'farmcraftadmin'

@secure()
param administratorLoginPassword string

@description('Existing subnet from control-plane.bicep, delegated to PostgreSQL Flexible Server.')
param postgresSubnetId string

@description('Existing private DNS zone from control-plane.bicep.')
param privateDnsZoneId string

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: serverName
  location: location
  tags: { app: 'FarmCraft', environment: 'staging', managedBy: 'bicep' }
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorLoginPassword
    version: '16'
    storage: { storageSizeGB: 32, autoGrow: 'Disabled' }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: {
      delegatedSubnetResourceId: postgresSubnetId
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

output serverFqdn string = server.properties.fullyQualifiedDomainName
output databaseName string = database.name
