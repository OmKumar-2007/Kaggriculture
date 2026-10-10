targetScope = 'resourceGroup'

@description('Region of the existing FarmCraft base resources.')
param location string = 'uaenorth'
@description('Existing Container Apps environment from control-plane.bicep.')
param environmentName string = 'farmcraft-environment'
@description('Existing Azure Storage account with a private artifacts container.')
param storageAccountName string
@description('Existing Azure Container Registry from control-plane.bicep.')
param registryName string
@description('Existing user-assigned image pull identity from control-plane.bicep.')
param pullIdentityName string = 'farmcraft-pull'
@description('A versioned, immutable API image built from the repository Dockerfile.')
param apiImage string
@description('Optional separate HTTPS frontend origin; empty for the same-origin SPA bundled into the API image.')
param frontendUrl string = ''
@secure()
@description('PostgreSQL SQLAlchemy URL from Azure Database for PostgreSQL Flexible Server.')
param databaseUrl string
@secure()
param adminPasswordHash string
@secure()
param adminSessionSecret string

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: environmentName
}
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}
resource blob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: storage
  name: 'default'
}
resource artifacts 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  parent: blob
  name: 'private-artifacts'
}
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}
resource pullIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: pullIdentityName
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'farmcraft-api'
  location: location
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: { '${pullIdentity.id}': {} }
  }
  tags: {
    app: 'FarmCraft'
    purpose: 'competition-api'
    managedBy: 'bicep'
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        { server: registry.properties.loginServer, identity: pullIdentity.id }
      ]
      ingress: {
        external: true
        allowInsecure: false
        targetPort: 8000
        transport: 'auto'
      }
      secrets: [
        { name: 'database-url', value: databaseUrl }
        { name: 'admin-password-hash', value: adminPasswordHash }
        { name: 'admin-session-secret', value: adminSessionSecret }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: apiImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'APP_ENV', value: 'production' }
            { name: 'QUEUE_BACKEND', value: 'postgres' }
            { name: 'SESSION_BACKEND', value: 'postgres' }
            { name: 'LOAD_TEST_FAKE_SIMULATION', value: '0' }
            { name: 'STORAGE_BACKEND', value: 'azure' }
            { name: 'AZURE_STORAGE_ACCOUNT_URL', value: 'https://${storage.name}.blob.${az.environment().suffixes.storage}' }
            { name: 'AZURE_STORAGE_CONTAINER', value: artifacts.name }
            { name: 'FARMCRAFT_EVALUATOR_VERSION', value: '2026.10.09' }
            { name: 'PUBLIC_BASE_URL', value: frontendUrl }
            { name: 'CORS_ORIGINS', value: frontendUrl }
            { name: 'DATABASE_URL', secretRef: 'database-url' }
            { name: 'ADMIN_PASSWORD_HASH', secretRef: 'admin-password-hash' }
            { name: 'ADMIN_SESSION_SECRET', secretRef: 'admin-session-secret' }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
}

resource blobWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(artifacts.id, api.id, 'blob-data-contributor')
  scope: artifacts
  properties: {
    principalId: api.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}

output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output apiPrincipalId string = api.identity.principalId
