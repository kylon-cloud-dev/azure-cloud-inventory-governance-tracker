"""Azure Resource Graph inventory collection.

This module discovers Azure resources across a target subscription using
DefaultAzureCredential. Locally, authentication uses the signed-in Azure CLI
session. In Azure Functions, it uses the Function App's managed identity.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions


RESOURCE_INVENTORY_QUERY = """
Resources
| project
    id,
    name,
    type,
    resourceGroup,
    subscriptionId,
    location,
    tags,
    sku,
    kind,
    properties
| order by id asc
"""


def get_target_subscription_id() -> str:
    """Return the Azure subscription ID configured for the scanner."""

    subscription_id = os.getenv("TARGET_SUBSCRIPTION_ID", "").strip()

    if not subscription_id:
        raise ValueError(
            "TARGET_SUBSCRIPTION_ID is not configured. "
            "Set it in the local environment or Function App settings."
        )

    return subscription_id


def normalize_resource(resource: dict[str, Any]) -> dict[str, Any]:
    """Normalize Resource Graph output into a predictable dictionary."""

    return {
        "id": resource.get("id", ""),
        "name": resource.get("name", ""),
        "type": str(resource.get("type", "")).lower(),
        "resource_group": resource.get("resourceGroup", ""),
        "subscription_id": resource.get("subscriptionId", ""),
        "location": resource.get("location", ""),
        "tags": resource.get("tags") or {},
        "sku": resource.get("sku") or {},
        "kind": resource.get("kind") or "",
        "properties": resource.get("properties") or {},
    }


def query_subscription_resources(
    subscription_id: str | None = None,
    credential: DefaultAzureCredential | None = None,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    """Query and return every Resource Graph resource in one subscription.

    Pagination is handled through the Resource Graph skip token so the scanner
    continues to work in subscriptions containing more than 1,000 resources.
    """

    target_subscription = subscription_id or get_target_subscription_id()

    if page_size < 1 or page_size > 1000:
        raise ValueError("page_size must be between 1 and 1000.")

    azure_credential = credential or DefaultAzureCredential()
    client = ResourceGraphClient(azure_credential)

    resources: list[dict[str, Any]] = []
    skip_token: str | None = None
    page_number = 0

    while True:
        page_number += 1

        options = QueryRequestOptions(
            top=page_size,
            skip_token=skip_token,
            result_format="objectArray",
        )

        request = QueryRequest(
            subscriptions=[target_subscription],
            query=RESOURCE_INVENTORY_QUERY,
            options=options,
        )

        logging.info("Querying Azure Resource Graph page %s.", page_number)

        response = client.resources(request)
        page_data = response.data or []

        if not isinstance(page_data, list):
            raise TypeError(
                "Resource Graph returned an unexpected response format. "
                "Expected objectArray data."
            )

        normalized_page = [
            normalize_resource(dict(resource))
            for resource in page_data
        ]

        resources.extend(normalized_page)

        logging.info(
            "Resource Graph page %s returned %s resources.",
            page_number,
            len(normalized_page),
        )

        skip_token = response.skip_token

        if not skip_token:
            break

    logging.info(
        "Inventory collection completed: %s resources across %s page(s).",
        len(resources),
        page_number,
    )

    return resources


def summarize_resource_types(
    resources: list[dict[str, Any]],
) -> dict[str, int]:
    """Return resource counts grouped by Azure resource type."""

    type_counts = Counter(
        resource.get("type", "unknown")
        for resource in resources
    )

    return dict(sorted(type_counts.items()))