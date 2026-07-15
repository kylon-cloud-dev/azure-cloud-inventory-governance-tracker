"""Unit tests for Azure governance checks."""

from scanner.governance import evaluate_inventory, summarize_findings


def test_detects_demo_governance_findings() -> None:
    resources = [
        {
            "id": "/subscriptions/demo/resourceGroups/rg-demo/providers/"
            "Microsoft.Network/publicIPAddresses/pip-demo",
            "name": "pip-demo",
            "type": "microsoft.network/publicipaddresses",
            "resource_group": "rg-demo",
            "location": "eastus",
            "tags": {"project": "governance-validation"},
            "properties": {
                "ipAddress": "203.0.113.10",
                "ipConfiguration": None,
            },
        },
        {
            "id": "/subscriptions/demo/resourceGroups/rg-demo/providers/"
            "Microsoft.Network/networkSecurityGroups/nsg-demo",
            "name": "nsg-demo",
            "type": "microsoft.network/networksecuritygroups",
            "resource_group": "rg-demo",
            "location": "eastus",
            "tags": {"project": "governance-validation"},
            "properties": {
                "securityRules": [
                    {
                        "name": "Allow-SSH-From-Internet",
                        "properties": {
                            "direction": "Inbound",
                            "access": "Allow",
                            "sourceAddressPrefix": "Internet",
                            "destinationPortRange": "22",
                        },
                    }
                ]
            },
        },
        {
            "id": "/subscriptions/demo/resourceGroups/rg-demo/providers/"
            "Microsoft.Storage/storageAccounts/stdemo",
            "name": "stdemo",
            "type": "microsoft.storage/storageaccounts",
            "resource_group": "rg-demo",
            "location": "eastus",
            "tags": {"project": "governance-validation"},
            "properties": {
                "allowBlobPublicAccess": True,
                "publicNetworkAccess": "Enabled",
            },
        },
    ]

    findings = evaluate_inventory(resources)
    check_ids = {finding["check_id"] for finding in findings}

    assert "TAG-001" in check_ids
    assert "NET-001" in check_ids
    assert "NET-002" in check_ids
    assert "NET-003" in check_ids
    assert "STG-001" in check_ids
    assert "STG-002" in check_ids

    summary = summarize_findings(findings)

    assert summary["High"] >= 2
    assert summary["Medium"] >= 1


def test_exempt_resource_produces_no_findings() -> None:
    resources = [
        {
            "id": "/subscriptions/demo/resourceGroups/rg-demo/providers/"
            "Microsoft.Storage/storageAccounts/sttracker",
            "name": "sttracker",
            "type": "microsoft.storage/storageaccounts",
            "resource_group": "rg-demo",
            "location": "eastus",
            "tags": {
                "governance_exempt": "true",
            },
            "properties": {
                "allowBlobPublicAccess": True,
                "publicNetworkAccess": "Enabled",
            },
        }
    ]

    assert evaluate_inventory(resources) == []


def test_system_managed_resources_skip_tag_findings() -> None:
    resources = [
        {
            "id": (
                "/subscriptions/demo/resourceGroups/NetworkWatcherRG/"
                "providers/Microsoft.Network/networkWatchers/"
                "NetworkWatcher_eastus"
            ),
            "name": "NetworkWatcher_eastus",
            "type": "microsoft.network/networkwatchers",
            "resource_group": "NetworkWatcherRG",
            "location": "eastus",
            "tags": {},
            "properties": {},
        },
        {
            "id": (
                "/subscriptions/demo/resourceGroups/rg-demo/providers/"
                "Microsoft.Insights/actionGroups/"
                "Application Insights Smart Detection"
            ),
            "name": "Application Insights Smart Detection",
            "type": "microsoft.insights/actiongroups",
            "resource_group": "rg-demo",
            "location": "global",
            "tags": {},
            "properties": {},
        },
    ]

    assert evaluate_inventory(resources) == []  