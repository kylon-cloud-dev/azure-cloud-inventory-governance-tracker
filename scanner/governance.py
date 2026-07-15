"""Governance and security checks for Azure resource inventory."""

from __future__ import annotations

from collections import Counter
from typing import Any


REQUIRED_TAGS = {
    "environment",
    "owner",
    "project",
    "managed_by",
}

INTERNET_SOURCE_PREFIXES = {
    "*",
    "internet",
    "0.0.0.0/0",
    "::/0",
}

HIGH_RISK_PORTS = {
    "22": "SSH",
    "3389": "RDP",
}

SEVERITY_ORDER = {
    "High": 1,
    "Medium": 2,
    "Low": 3,
    "Informational": 4,
}

TAG_CHECK_EXEMPT_RESOURCE_TYPES = {
    "microsoft.network/networkwatchers",
}

TAG_CHECK_EXEMPT_RESOURCES = {
    (
        "microsoft.insights/actiongroups",
        "application insights smart detection",
    ),
}

def _normalized_tags(resource: dict[str, Any]) -> dict[str, str]:
    """Return tags with lowercase keys for case-insensitive checks."""

    tags = resource.get("tags") or {}

    return {
        str(key).lower(): str(value)
        for key, value in tags.items()
    }


def _is_exempt(resource: dict[str, Any]) -> bool:
    """Return True when a resource is intentionally exempt from scanning."""

    tags = _normalized_tags(resource)

    return tags.get("governance_exempt", "").lower() == "true"


def _skip_required_tag_check(resource: dict[str, Any]) -> bool:
    """Exclude Azure-managed resources from required-tag evaluation."""

    resource_type = str(resource.get("type", "")).lower()
    resource_name = str(resource.get("name", "")).lower()

    if resource_type in TAG_CHECK_EXEMPT_RESOURCE_TYPES:
        return True

    return (
        resource_type,
        resource_name,
    ) in TAG_CHECK_EXEMPT_RESOURCES


def _create_finding(
    resource: dict[str, Any],
    check_id: str,
    severity: str,
    category: str,
    title: str,
    description: str,
    recommendation: str,
    evidence: str,
) -> dict[str, Any]:
    """Create a finding using a consistent schema."""

    return {
        "check_id": check_id,
        "severity": severity,
        "category": category,
        "title": title,
        "description": description,
        "recommendation": recommendation,
        "evidence": evidence,
        "resource_name": resource.get("name", ""),
        "resource_type": resource.get("type", ""),
        "resource_group": resource.get("resource_group", ""),
        "location": resource.get("location", ""),
        "resource_id": resource.get("id", ""),
    }


def check_required_tags(
    resource: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect resources missing required governance tags."""

    if _is_exempt(resource) or _skip_required_tag_check(resource):
        return []

    tags = _normalized_tags(resource)
    missing_tags = sorted(REQUIRED_TAGS - set(tags))

    if not missing_tags:
        return []

    return [
        _create_finding(
            resource=resource,
            check_id="TAG-001",
            severity="Medium",
            category="Tagging",
            title="Required governance tags are missing",
            description=(
                "The resource does not contain all required ownership and "
                "lifecycle-management tags."
            ),
            recommendation=(
                "Add the required environment, owner, project, and managed_by "
                "tags through Terraform or Azure Policy."
            ),
            evidence=f"Missing tags: {', '.join(missing_tags)}",
        )
    ]


def check_public_ip(
    resource: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect public IP resources and unattached public IP addresses."""

    if resource.get("type") != "microsoft.network/publicipaddresses":
        return []

    if _is_exempt(resource):
        return []

    properties = resource.get("properties") or {}
    findings = [
        _create_finding(
            resource=resource,
            check_id="NET-001",
            severity="Medium",
            category="Network Exposure",
            title="Public IP address exists",
            description=(
                "A public IP increases the externally reachable attack surface "
                "and should have a documented business requirement."
            ),
            recommendation=(
                "Confirm that public connectivity is required. Prefer private "
                "endpoints, private IP addressing, or a controlled ingress "
                "service when possible."
            ),
            evidence=(
                f"IP address: {properties.get('ipAddress') or 'not assigned'}"
            ),
        )
    ]

    ip_configuration = properties.get("ipConfiguration")
    nat_gateway = properties.get("natGateway")

    if not ip_configuration and not nat_gateway:
        findings.append(
            _create_finding(
                resource=resource,
                check_id="NET-002",
                severity="Medium",
                category="Resource Hygiene",
                title="Public IP address is unassociated",
                description=(
                    "The public IP does not appear to be attached to a network "
                    "interface, load balancer, gateway, or NAT gateway."
                ),
                recommendation=(
                    "Delete the unused public IP to reduce unnecessary exposure "
                    "and avoid ongoing resource charges."
                ),
                evidence="No ipConfiguration or natGateway association found.",
            )
        )

    return findings


def _get_rule_values(
    properties: dict[str, Any],
    singular_key: str,
    plural_key: str,
) -> list[str]:
    """Return normalized values from singular or plural NSG rule fields."""

    values: list[str] = []

    singular_value = properties.get(singular_key)

    if singular_value is not None:
        values.append(str(singular_value))

    plural_value = properties.get(plural_key) or []

    if isinstance(plural_value, list):
        values.extend(str(value) for value in plural_value)

    return [value.lower() for value in values]


def _port_range_is_high_risk(port_range: str) -> tuple[bool, str]:
    """Determine whether a destination port expression includes SSH or RDP."""

    normalized = port_range.strip().lower()

    if normalized == "*":
        return True, "all destination ports"

    if normalized in HIGH_RISK_PORTS:
        return True, f"{HIGH_RISK_PORTS[normalized]} port {normalized}"

    if "-" in normalized:
        start_text, end_text = normalized.split("-", maxsplit=1)

        try:
            start_port = int(start_text)
            end_port = int(end_text)
        except ValueError:
            return False, ""

        exposed_services = [
            f"{service} port {port}"
            for port, service in HIGH_RISK_PORTS.items()
            if start_port <= int(port) <= end_port
        ]

        if exposed_services:
            return True, ", ".join(exposed_services)

    return False, ""


def check_nsg_rules(
    resource: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect risky inbound NSG rules that expose administrative ports."""

    if resource.get("type") != "microsoft.network/networksecuritygroups":
        return []

    if _is_exempt(resource):
        return []

    properties = resource.get("properties") or {}
    security_rules = properties.get("securityRules") or []
    findings: list[dict[str, Any]] = []

    for rule in security_rules:
        rule_name = rule.get("name", "unnamed-rule")
        rule_properties = rule.get("properties") or {}

        direction = str(rule_properties.get("direction", "")).lower()
        access = str(rule_properties.get("access", "")).lower()

        if direction != "inbound" or access != "allow":
            continue

        sources = _get_rule_values(
            rule_properties,
            "sourceAddressPrefix",
            "sourceAddressPrefixes",
        )

        internet_exposed = any(
            source in INTERNET_SOURCE_PREFIXES
            for source in sources
        )

        if not internet_exposed:
            continue

        destination_ports = _get_rule_values(
            rule_properties,
            "destinationPortRange",
            "destinationPortRanges",
        )

        for destination_port in destination_ports:
            high_risk, exposed_service = _port_range_is_high_risk(
                destination_port
            )

            if not high_risk:
                continue

            findings.append(
                _create_finding(
                    resource=resource,
                    check_id="NET-003",
                    severity="High",
                    category="Network Exposure",
                    title="Administrative port exposed to the Internet",
                    description=(
                        f"NSG rule {rule_name} permits inbound Internet traffic "
                        f"to {exposed_service}."
                    ),
                    recommendation=(
                        "Restrict the source to approved administrative IP "
                        "ranges, use Azure Bastion or private connectivity, and "
                        "apply least-privilege network rules."
                    ),
                    evidence=(
                        f"Rule={rule_name}; Sources={sources}; "
                        f"DestinationPorts={destination_ports}"
                    ),
                )
            )

            break

    return findings


def check_storage_account(
    resource: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect potentially unsafe Azure Storage network configurations."""

    if resource.get("type") != "microsoft.storage/storageaccounts":
        return []

    if _is_exempt(resource):
        return []

    properties = resource.get("properties") or {}
    findings: list[dict[str, Any]] = []

    allow_blob_public_access = properties.get("allowBlobPublicAccess")

    if allow_blob_public_access is True:
        findings.append(
            _create_finding(
                resource=resource,
                check_id="STG-001",
                severity="High",
                category="Data Exposure",
                title="Anonymous blob access is permitted",
                description=(
                    "The storage account allows containers or blobs to be "
                    "configured for anonymous public access."
                ),
                recommendation=(
                    "Disable allowBlobPublicAccess unless anonymous access is "
                    "explicitly required and approved."
                ),
                evidence="properties.allowBlobPublicAccess=true",
            )
        )

    public_network_access = str(
        properties.get("publicNetworkAccess", "Enabled")
    )

    if public_network_access.lower() != "disabled":
        findings.append(
            _create_finding(
                resource=resource,
                check_id="STG-002",
                severity="Medium",
                category="Network Exposure",
                title="Storage public network access is enabled",
                description=(
                    "The storage account is reachable through its public "
                    "endpoint, subject to its firewall and authorization rules."
                ),
                recommendation=(
                    "Review whether public connectivity is required. Prefer "
                    "private endpoints or restricted network rules."
                ),
                evidence=(
                    f"properties.publicNetworkAccess={public_network_access}"
                ),
            )
        )

    return findings


def check_key_vault(
    resource: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect Key Vaults with public network connectivity enabled."""

    if resource.get("type") != "microsoft.keyvault/vaults":
        return []

    if _is_exempt(resource):
        return []

    properties = resource.get("properties") or {}
    public_network_access = str(
        properties.get("publicNetworkAccess", "Enabled")
    )

    if public_network_access.lower() == "disabled":
        return []

    return [
        _create_finding(
            resource=resource,
            check_id="KV-001",
            severity="Medium",
            category="Network Exposure",
            title="Key Vault public network access is enabled",
            description=(
                "The Key Vault can be reached through its public endpoint, "
                "subject to firewall rules and identity authorization."
            ),
            recommendation=(
                "Evaluate private endpoint connectivity or restrict public "
                "network access to approved networks."
            ),
            evidence=(
                f"properties.publicNetworkAccess={public_network_access}"
            ),
        )
    ]


def evaluate_resource(
    resource: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run every governance rule against one Azure resource."""

    findings: list[dict[str, Any]] = []

    findings.extend(check_required_tags(resource))
    findings.extend(check_public_ip(resource))
    findings.extend(check_nsg_rules(resource))
    findings.extend(check_storage_account(resource))
    findings.extend(check_key_vault(resource))

    return findings


def evaluate_inventory(
    resources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Evaluate all resources and return severity-sorted findings."""

    findings: list[dict[str, Any]] = []

    for resource in resources:
        findings.extend(evaluate_resource(resource))

    return sorted(
        findings,
        key=lambda finding: (
            SEVERITY_ORDER.get(finding["severity"], 99),
            finding["resource_type"],
            finding["resource_name"],
            finding["check_id"],
        ),
    )


def summarize_findings(
    findings: list[dict[str, Any]],
) -> dict[str, int]:
    """Return finding totals grouped by severity."""

    severity_counts = Counter(
        finding.get("severity", "Unknown")
        for finding in findings
    )

    return {
        severity: severity_counts.get(severity, 0)
        for severity in SEVERITY_ORDER
    }