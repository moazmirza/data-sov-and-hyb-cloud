targetScope = 'resourceGroup'

@description('Location for deployed resources')
param location string = resourceGroup().location

@description('Environment suffix, for example dev, test, or prod')
param environment string = 'dev'

@description('Application name prefix used for resource naming')
param appName string = 'contoso-sov'

var tags = {
	workload: 'sovereignty-compliance-reference'
	environment: environment
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
	name: '${appName}-law-${environment}'
	location: location
	tags: tags
	properties: {
		retentionInDays: 30
		sku: {
			name: 'PerGB2018'
		}
	}
}

output logAnalyticsWorkspaceId string = logAnalytics.id
