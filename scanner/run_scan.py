"""Command-line entry point for the Azure governance scanner.

Designed to run from GitHub Actions after authentication through Azure OIDC.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

from azure.identity import AzureCliCredential

from governance import evaluate_inventory, summarize_findings
from inventory import query_subscription_resources
from reporting import build_report_files, upload_report_files


def require_environment_variable(name: str) -> str:
    """Return a required environment variable or raise a clear error."""

    value = os.getenv(name, "").strip()

    if not value:
        raise ValueError(f"{name} is not configured.")

    return value


def run_scan() -> dict[str, Any]:
    """Collect Azure inventory, evaluate it, and upload reports."""

    subscription_id = require_environment_variable(
        "TARGET_SUBSCRIPTION_ID"
    )

    storage_account_url = require_environment_variable(
        "REPORT_STORAGE_ACCOUNT_URL"
    )

    report_container = os.getenv(
        "REPORT_CONTAINER_NAME",
        "inventory-reports",
    ).strip()

    credential = AzureCliCredential()

    logging.info("Querying Azure Resource Graph.")

    resources = query_subscription_resources(
        subscription_id=subscription_id,
        credential=credential,
    )

    findings = evaluate_inventory(resources)
    severity_summary = summarize_findings(findings)
    report_files = build_report_files(resources, findings)

    uploaded_blobs = upload_report_files(
        account_url=storage_account_url,
        container_name=report_container,
        report_files=report_files,
        credential=credential,
    )

    return {
        "status": "success",
        "execution_source": "github-actions",
        "resources_scanned": len(resources),
        "total_findings": len(findings),
        "findings_by_severity": severity_summary,
        "uploaded_blob_count": len(uploaded_blobs),
        "uploaded_blobs": uploaded_blobs,
    }


def main() -> int:
    """Run the scanner and print a structured workflow summary."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        result = run_scan()
    except Exception as error:
        logging.exception("Governance scan failed.")

        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": str(error),
                },
                indent=2,
            )
        )

        return 1

    print(json.dumps(result, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())