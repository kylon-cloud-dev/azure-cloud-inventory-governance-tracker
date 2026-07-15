output "resource_group_name" {
  description = "Resource group containing the tracker infrastructure."
  value       = azurerm_resource_group.main.name
}

output "function_app_name" {
  description = "Name of the Azure Function App."
  value       = azurerm_linux_function_app.tracker.name
}

output "function_app_url" {
  description = "Default Function App URL."
  value       = "https://${azurerm_linux_function_app.tracker.default_hostname}"
}

output "storage_account_name" {
  description = "Storage account containing deployment packages and reports."
  value       = azurerm_storage_account.tracker.name
}

output "report_container_name" {
  description = "Private container holding generated governance reports."
  value       = azurerm_storage_container.reports.name
}

output "log_analytics_workspace_name" {
  description = "Log Analytics workspace used for Function telemetry."
  value       = azurerm_log_analytics_workspace.main.name
}

output "application_insights_name" {
  description = "Application Insights component used for monitoring."
  value       = azurerm_application_insights.main.name
}

output "demo_resources" {
  description = "Known test conditions created for governance validation."

  value = var.enable_demo_findings ? {
    public_ip       = azurerm_public_ip.demo_unassociated[0].name
    network_nsg     = azurerm_network_security_group.demo[0].name
    storage_account = azurerm_storage_account.demo_public[0].name
  } : null
}