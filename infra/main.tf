locals {
  clean_prefix = replace(var.name_prefix, "-", "")

  tracker_tags = merge(var.tags, {
    governance_exempt = "true"
  })

  demo_tags = {
    project = "governance-validation"
  }
}

# Creates a stable suffix for globally unique Azure resource names.
resource "random_string" "suffix" {
  length  = 5
  special = false
  upper   = false
  numeric = true
}

# -----------------------------------------------------------------------------
# Core tracker infrastructure
# -----------------------------------------------------------------------------

resource "azurerm_resource_group" "main" {
  name     = "rg-${var.name_prefix}-${random_string.suffix.result}"
  location = var.location
  tags     = local.tracker_tags
}

resource "azurerm_storage_account" "tracker" {
  name                     = "st${local.clean_prefix}${random_string.suffix.result}"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"

  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  public_network_access_enabled   = true

  # The deployment container uses an account connection string.
  shared_access_key_enabled       = true
  default_to_oauth_authentication = true

  blob_properties {
    versioning_enabled = true

    delete_retention_policy {
      days = 7
    }

    container_delete_retention_policy {
      days = 7
    }
  }

  tags = local.tracker_tags
}


# The Python scanner uploads CSV, JSON, and Markdown reports here.
resource "azurerm_storage_container" "reports" {
  name                  = var.report_container_name
  storage_account_id    = azurerm_storage_account.tracker.id
  container_access_type = "private"
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "law-${var.name_prefix}-${random_string.suffix.result}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = local.tracker_tags
}

resource "azurerm_application_insights" "main" {
  name                = "appi-${var.name_prefix}-${random_string.suffix.result}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"

  tags = local.tracker_tags
}

resource "azurerm_service_plan" "function_linux" {
  name                = "asp-lnx-cu-${var.name_prefix}-${random_string.suffix.result}"
  location            = var.function_location
  resource_group_name = azurerm_resource_group.main.name
  os_type             = "Linux"
  sku_name            = "Y1"

  tags = local.tracker_tags
}

resource "azurerm_linux_function_app" "tracker" {
  name                = "func-lnx-${var.name_prefix}-${random_string.suffix.result}"
  location            = var.function_location
  resource_group_name = azurerm_resource_group.main.name
  service_plan_id     = azurerm_service_plan.function_linux.id

  storage_account_name       = azurerm_storage_account.tracker.name
  storage_account_access_key = azurerm_storage_account.tracker.primary_access_key

  functions_extension_version = "~4"
  https_only                  = true

  identity {
    type = "SystemAssigned"
  }

  site_config {
    application_stack {
      python_version = "3.12"
    }
  }

  app_settings = {
    FUNCTIONS_WORKER_RUNTIME = "python"

    AzureWebJobsFeatureFlags = "EnableWorkerIndexing"

    AzureWebJobsStorage = azurerm_storage_account.tracker.primary_connection_string

    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.main.connection_string

    SCM_DO_BUILD_DURING_DEPLOYMENT = "true"
    ENABLE_ORYX_BUILD              = "true"

    TARGET_SUBSCRIPTION_ID     = data.azurerm_client_config.current.subscription_id
    REPORT_STORAGE_ACCOUNT_URL = azurerm_storage_account.tracker.primary_blob_endpoint
    REPORT_CONTAINER_NAME      = azurerm_storage_container.reports.name
    TIMER_SCHEDULE             = "0 0 12 * * *"
    GOVERNANCE_EXEMPT_TAG      = "governance_exempt"
    SCANNER_RESOURCE_GROUP     = azurerm_resource_group.main.name
  }

  tags = local.tracker_tags
}

# Gives the Function read-only control-plane visibility across the subscription.
resource "azurerm_role_assignment" "function_subscription_reader" {
  scope                = data.azurerm_subscription.current.id
  role_definition_name = "Reader"
  principal_id         = azurerm_linux_function_app.tracker.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

# Lets the Function upload reports using its managed identity.
resource "azurerm_role_assignment" "function_blob_contributor" {
  scope                = azurerm_storage_account.tracker.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_linux_function_app.tracker.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

# -----------------------------------------------------------------------------
# Governance validation resources
#
# These resources are intentionally configured to produce known findings.
# Nothing is attached to a VM and no public data container is created.
# -----------------------------------------------------------------------------

resource "azurerm_public_ip" "demo_unassociated" {
  count = var.enable_demo_findings ? 1 : 0

  name                = "pip-governance-demo"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  allocation_method   = "Static"
  sku                 = "Standard"

  # Intentionally missing owner, environment, and managed_by tags.
  tags = local.demo_tags
}

resource "azurerm_network_security_group" "demo" {
  count = var.enable_demo_findings ? 1 : 0

  name                = "nsg-governance-demo"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  # Intentionally incomplete tags.
  tags = local.demo_tags
}

resource "azurerm_network_security_rule" "demo_ssh_from_internet" {
  count = var.enable_demo_findings ? 1 : 0

  name                        = "Allow-SSH-From-Internet"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "22"
  source_address_prefix       = "Internet"
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.main.name
  network_security_group_name = azurerm_network_security_group.demo[0].name
}

resource "azurerm_storage_account" "demo_public" {
  count = var.enable_demo_findings ? 1 : 0

  name                     = "stdemo${random_string.suffix.result}"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"

  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  public_network_access_enabled   = true
  allow_nested_items_to_be_public = true
  shared_access_key_enabled       = true

  # Intentionally incomplete tags.
  tags = local.demo_tags
}