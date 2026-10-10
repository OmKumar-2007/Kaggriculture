@description('Dedicated outbound-only FarmCraft evaluator VM. No database, registry, or web app.')
param location string = 'koreacentral'
param name string = 'farmcraft-eval-01'
param vmSize string = 'Standard_D2as_v4'
param adminUsername string = 'farmcraftadmin'
param adminSshPublicKey string
@secure()
param cloudInit string

resource nsg 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: '${name}-nsg'
  location: location
  properties: {
    securityRules: []
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: '${name}-vnet'
  location: location
  properties: {
    addressSpace: { addressPrefixes: [ '10.87.0.0/24' ] }
    subnets: [
      {
        name: 'workers'
        properties: {
          addressPrefix: '10.87.0.0/25'
          networkSecurityGroup: { id: nsg.id }
        }
      }
    ]
  }
}

resource pip 'Microsoft.Network/publicIPAddresses@2023-11-01' = {
  name: '${name}-egress-ip'
  location: location
  sku: { name: 'Standard' }
  properties: { publicIPAllocationMethod: 'Static' }
}

resource nic 'Microsoft.Network/networkInterfaces@2023-11-01' = {
  name: '${name}-nic'
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'primary'
        properties: {
          primary: true
          subnet: { id: vnet.properties.subnets[0].id }
          publicIPAddress: { id: pip.id }
        }
      }
    ]
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
  name: name
  location: location
  properties: {
    hardwareProfile: { vmSize: vmSize }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        deleteOption: 'Delete'
        diskSizeGB: 32
        managedDisk: { storageAccountType: 'Standard_LRS' }
      }
    }
    osProfile: {
      computerName: name
      adminUsername: adminUsername
      customData: base64(cloudInit)
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: { publicKeys: [ { path: '/home/${adminUsername}/.ssh/authorized_keys', keyData: adminSshPublicKey } ] }
      }
    }
    networkProfile: { networkInterfaces: [ { id: nic.id, properties: { primary: true, deleteOption: 'Delete' } } ] }
    securityProfile: { securityType: 'TrustedLaunch' }
  }
  tags: { app: 'FarmCraft', role: 'isolated-evaluator', lifecycle: 'deallocate-after-event' }
}

output vmName string = vm.name
output vmId string = vm.id
