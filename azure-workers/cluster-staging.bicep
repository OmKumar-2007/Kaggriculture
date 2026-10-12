targetScope = 'subscription'

@description('Dedicated staging evaluator resource group. Never targets the existing production evaluator.')
param resourceGroupName string = 'rg-farmcraft-evaluators-20261012'
param resourceGroupLocation string = 'koreacentral'
param koreaVmName string = 'farmcraft-eval-02'
param indonesiaVmName string = 'farmcraft-eval-03'
param koreaVmSize string = 'Standard_D4s_v4'
param indonesiaVmSize string = 'Standard_D4as_v4'
param adminSshPublicKey string
@secure()
param cloudInit string

resource evaluatorGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: resourceGroupLocation
  tags: { app: 'FarmCraft', environment: 'staging', purpose: 'evaluator-cluster' }
}

module koreaVm './worker.bicep' = {
  name: 'farmcraft-eval-02-staging'
  scope: evaluatorGroup
  params: {
    location: 'koreacentral'
    name: koreaVmName
    vmSize: koreaVmSize
    adminSshPublicKey: adminSshPublicKey
    cloudInit: cloudInit
  }
}

module indonesiaVm './worker.bicep' = {
  name: 'farmcraft-eval-03-staging'
  scope: evaluatorGroup
  params: {
    location: 'indonesiacentral'
    name: indonesiaVmName
    vmSize: indonesiaVmSize
    adminSshPublicKey: adminSshPublicKey
    cloudInit: cloudInit
  }
}

output resourceGroup string = evaluatorGroup.name
output koreaVmId string = koreaVm.outputs.vmId
output indonesiaVmId string = indonesiaVm.outputs.vmId
output koreaPrincipalId string = koreaVm.outputs.principalId
output indonesiaPrincipalId string = indonesiaVm.outputs.principalId
