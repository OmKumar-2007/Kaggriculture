targetScope = 'resourceGroup'

// Staging only. Deploy to a new resource group after the provisioning approval.
param location string = resourceGroup().location
param appName string
param environmentName string
param registryName string
param pullIdentityName string
param storageAccountName string
param image string
@secure()
param databaseUrl string
@secure()
param adminPasswordHash string
@secure()
param adminSessionSecret string
@minValue(0)
@maxValue(3)
param minReplicas int = 0

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' existing = { name: environmentName }
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = { name: registryName }
resource pullIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = { name: pullIdentityName }
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = { name: storageAccountName }
resource blob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = { parent: storage, name: 'default' }
resource artifacts 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = { parent: blob, name: 'private-artifacts' }

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: { '${pullIdentity.id}': {} }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [{ server: registry.properties.loginServer, identity: pullIdentity.id }]
      ingress: { external: true, allowInsecure: false, targetPort: 8000, transport: 'auto' }
      secrets: [
        { name: 'database-url', value: databaseUrl }
        { name: 'admin-password-hash', value: adminPasswordHash }
        { name: 'admin-session-secret', value: adminSessionSecret }
      ]
    }
    template: {
      containers: [{
        name: 'farmcraft'
        image: image
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'APP_ENV', value: 'production' }
          { name: 'QUEUE_BACKEND', value: 'postgres' }
          { name: 'SESSION_BACKEND', value: 'postgres' }
          { name: 'SIMULATION_WORKERS', value: '0' }
          { name: 'FARMCRAFT_EVALUATOR_VERSION', value: '2026.10.12' }
          { name: 'STORAGE_BACKEND', value: 'azure' }
          { name: 'AZURE_STORAGE_ACCOUNT_URL', value: 'https://${storage.name}.blob.${az.environment().suffixes.storage}' }
          { name: 'AZURE_STORAGE_CONTAINER', value: artifacts.name }
          { name: 'DATABASE_URL', secretRef: 'database-url' }
          { name: 'ADMIN_PASSWORD_HASH', secretRef: 'admin-password-hash' }
          { name: 'ADMIN_SESSION_SECRET', secretRef: 'admin-session-secret' }
        ]
        probes: [
          { type: 'Liveness', httpGet: { path: '/health', port: 8000 }, initialDelaySeconds: 20, periodSeconds: 20 }
          { type: 'Readiness', httpGet: { path: '/ready', port: 8000 }, initialDelaySeconds: 15, periodSeconds: 15 }
        ]
      }]
      scale: { minReplicas: minReplicas, maxReplicas: 2 }
    }
  }
}

resource blobWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(artifacts.id, app.id, 'blob-data-contributor')
  scope: artifacts
  properties: {
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}

output appUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
