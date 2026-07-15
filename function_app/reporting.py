"""Report generation and Azure Blob Storage upload helpers."""

from __future__ import annotations

import csv
import io
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings


INVENTORY_CSV_FIELDS = [
    "name",
    "type",
    "resource_group",
    "location",
    "kind",
    "tags",
    "sku",
    "id",
]

FINDINGS_CSV_FIELDS = [
    "check_id",
    "severity",
    "category",
    "title",
    "resource_name",
    "resource_type",
    "resource_group",
    "location",
    "description",
    "evidence",
    "recommendation",
    "resource_id",
]


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


def _serialize_value(value: Any) -> str:
    """Convert nested values into stable JSON text for CSV output."""

    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)

    if value is None:
        return ""

    return str(value)


def create_inventory_csv(resources: list[dict[str, Any]]) -> bytes:
    """Create a CSV inventory report."""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=INVENTORY_CSV_FIELDS)
    writer.writeheader()

    for resource in resources:
        writer.writerow(
            {
                field: _serialize_value(resource.get(field))
                for field in INVENTORY_CSV_FIELDS
            }
        )

    return output.getvalue().encode("utf-8")


def create_findings_csv(findings: list[dict[str, Any]]) -> bytes:
    """Create a CSV governance-findings report."""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FINDINGS_CSV_FIELDS)
    writer.writeheader()

    for finding in findings:
        writer.writerow(
            {
                field: _serialize_value(finding.get(field))
                for field in FINDINGS_CSV_FIELDS
            }
        )

    return output.getvalue().encode("utf-8")


def build_summary(
    resources: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build overall inventory and governance statistics."""

    resource_types = Counter(
        resource.get("type", "unknown")
        for resource in resources
    )

    severities = Counter(
        finding.get("severity", "Unknown")
        for finding in findings
    )

    categories = Counter(
        finding.get("category", "Unknown")
        for finding in findings
    )

    return {
        "total_resources": len(resources),
        "total_findings": len(findings),
        "findings_by_severity": {
            "High": severities.get("High", 0),
            "Medium": severities.get("Medium", 0),
            "Low": severities.get("Low", 0),
            "Informational": severities.get("Informational", 0),
        },
        "findings_by_category": dict(sorted(categories.items())),
        "resources_by_type": dict(sorted(resource_types.items())),
    }


def create_json_report(
    resources: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    generated_at: datetime,
) -> bytes:
    """Create a complete machine-readable JSON report."""

    payload = {
        "generated_at_utc": generated_at.isoformat(),
        "summary": build_summary(resources, findings),
        "resources": resources,
        "findings": findings,
    }

    return json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        default=str,
    ).encode("utf-8")


def create_markdown_summary(
    resources: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    generated_at: datetime,
) -> bytes:
    """Create a human-readable Markdown governance summary."""

    summary = build_summary(resources, findings)
    severity_counts = summary["findings_by_severity"]

    lines = [
        "# Azure Cloud Inventory and Governance Report",
        "",
        f"**Generated:** {generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Executive Summary",
        "",
        f"- Resources inventoried: **{summary['total_resources']}**",
        f"- Governance findings: **{summary['total_findings']}**",
        f"- High severity: **{severity_counts['High']}**",
        f"- Medium severity: **{severity_counts['Medium']}**",
        f"- Low severity: **{severity_counts['Low']}**",
        "",
        "## Resource Inventory by Type",
        "",
        "| Resource type | Count |",
        "|---|---:|",
    ]

    for resource_type, count in summary["resources_by_type"].items():
        lines.append(f"| `{resource_type}` | {count} |")

    lines.extend(
        [
            "",
            "## Governance Findings",
            "",
        ]
    )

    if not findings:
        lines.append("No governance findings were detected.")
    else:
        lines.extend(
            [
                "| Severity | Check | Resource | Finding |",
                "|---|---|---|---|",
            ]
        )

        for finding in findings:
            lines.append(
                "| {severity} | `{check_id}` | `{resource}` | {title} |".format(
                    severity=finding.get("severity", ""),
                    check_id=finding.get("check_id", ""),
                    resource=finding.get("resource_name", ""),
                    title=finding.get("title", "").replace("|", "\\|"),
                )
            )

        lines.extend(
            [
                "",
                "## Detailed Recommendations",
                "",
            ]
        )

        for index, finding in enumerate(findings, start=1):
            lines.extend(
                [
                    f"### {index}. {finding.get('title', 'Finding')}",
                    "",
                    f"- **Severity:** {finding.get('severity', '')}",
                    f"- **Check ID:** `{finding.get('check_id', '')}`",
                    f"- **Resource:** `{finding.get('resource_name', '')}`",
                    f"- **Type:** `{finding.get('resource_type', '')}`",
                    f"- **Evidence:** {finding.get('evidence', '')}",
                    f"- **Recommendation:** {finding.get('recommendation', '')}",
                    "",
                ]
            )

    return "\n".join(lines).encode("utf-8")


def build_report_files(
    resources: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, bytes]:
    """Build all report formats generated by one scan."""

    report_time = generated_at or _utc_now()

    return {
        "inventory.csv": create_inventory_csv(resources),
        "findings.csv": create_findings_csv(findings),
        "governance-report.json": create_json_report(
            resources,
            findings,
            report_time,
        ),
        "summary.md": create_markdown_summary(
            resources,
            findings,
            report_time,
        ),
    }


def upload_report_files(
    account_url: str,
    container_name: str,
    report_files: dict[str, bytes],
    generated_at: datetime | None = None,
    credential: DefaultAzureCredential | None = None,
) -> list[str]:
    """Upload timestamped and latest report files using managed identity."""

    report_time = generated_at or _utc_now()
    timestamp = report_time.strftime("%Y%m%dT%H%M%SZ")
    dated_prefix = report_time.strftime("scans/%Y/%m/%d")

    azure_credential = credential or DefaultAzureCredential()
    blob_service = BlobServiceClient(
        account_url=account_url,
        credential=azure_credential,
    )

    container_client = blob_service.get_container_client(container_name)
    uploaded_blobs: list[str] = []

    content_types = {
        ".csv": "text/csv",
        ".json": "application/json",
        ".md": "text/markdown",
    }

    for filename, content in report_files.items():
        extension = f".{filename.rsplit('.', maxsplit=1)[-1]}"
        content_type = content_types.get(
            extension,
            "application/octet-stream",
        )

        blob_names = [
            f"{dated_prefix}/{timestamp}/{filename}",
            f"latest/{filename}",
        ]

        for blob_name in blob_names:
            blob_client = container_client.get_blob_client(blob_name)

            blob_client.upload_blob(
                content,
                overwrite=True,
                content_settings=ContentSettings(
                    content_type=content_type,
                    content_encoding="utf-8",
                ),
            )

            uploaded_blobs.append(blob_name)
            logging.info("Uploaded governance report blob: %s", blob_name)

    return uploaded_blobs