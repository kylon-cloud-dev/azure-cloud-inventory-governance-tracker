variable "location" {
  description = "Azure region used for the tracker infrastructure."
  type        = string
  default     = "eastus"
}

variable "function_location" {
  description = "Azure region used for the Linux Consumption Function App."
  type        = string
  default     = "centralus"
}

variable "name_prefix" {
  description = "Short prefix used when naming Azure resources."
  type        = string
  default     = "cigtkylon"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,15}$", var.name_prefix))
    error_message = "name_prefix must contain 3-15 lowercase letters, numbers, or hyphens."
  }
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "lab"
}

variable "report_container_name" {
  description = "Private Blob container used to store generated inventory reports."
  type        = string
  default     = "inventory-reports"
}

variable "enable_demo_findings" {
  description = "Deploy intentionally noncompliant lab resources used to verify governance checks."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Standard tags applied to the tracker infrastructure."
  type        = map(string)

  default = {
    project     = "azure-cloud-inventory-governance-tracker"
    environment = "lab"
    owner       = "kylon"
    managed_by  = "terraform"
  }
}