"""Azure Function entry points for inventory and governance scans."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import azure.functions as func


app = func.FunctionApp()


def run_governance_scan(trigger_source: str) -> dict[str, Any]:
    """Collect inventory, evaluate governance, and upload reports."""

    # Import application dependencies after function indexing.
    # This prevents an Azure SDK import problem from hiding every trigger.
    from governance import evaluate_inventory, summarize_findings
    from inventory import query_subscription_resources
    from reporting import build_report_files, upload_report_files

    storage_account_url = os.getenv(
        "REPORT_STORAGE_ACCOUNT_URL",
        "",
    ).strip()

    if not storage_account_url:
        raise ValueError("REPORT_STORAGE_ACCOUNT_URL is not configured.")

    if not report_container:
        raise ValueError("REPORT_CONTAINER_NAME is not configured.")

    logging.info(
        "Starting Azure inventory scan. Trigger source: %s",
        trigger_source,
    )

    resources = query_subscription_resources()
    findings = evaluate_inventory(resources)
    severity_summary = summarize_findings(findings)

    report_files = build_report_files(resources, findings)

    uploaded_blobs = upload_report_files(
        account_url=storage_account_url,
        container_name=report_container,
        report_files=report_files,
    )

    result = {
        "status": "success",
        "trigger_source": trigger_source,
        "resources_scanned": len(resources),
        "total_findings": len(findings),
        "findings_by_severity": severity_summary,
        "uploaded_blob_count": len(uploaded_blobs),
        "uploaded_blobs": uploaded_blobs,
    }

    logging.info(
        "GOVERNANCE_SCAN_SUMMARY "
        "resources=%s findings=%s high=%s medium=%s low=%s blobs=%s",
        len(resources),
        len(findings),
        severity_summary["High"],
        severity_summary["Medium"],
        severity_summary["Low"],
        len(uploaded_blobs),
    )

    return result


@app.timer_trigger(
    schedule="%TIMER_SCHEDULE%",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def scheduled_inventory_scan(timer: func.TimerRequest) -> None:
    """Run the production inventory scan on a recurring schedule."""

    if timer.past_due:
        logging.warning("The inventory timer invocation is past due.")

    try:
        run_governance_scan(trigger_source="timer")
    except Exception:
        logging.exception("Scheduled governance scan failed.")
        raise


@app.route(
    route="scan",
    methods=["POST"],
    auth_level=func.AuthLevel.FUNCTION,
)
def manual_inventory_scan(
    request: func.HttpRequest,
) -> func.HttpResponse:
    """Run a secured on-demand scan for testing and verification."""

    try:
        result = run_governance_scan(trigger_source="http")

        return func.HttpResponse(
            body=json.dumps(result, indent=2),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as error:
        logging.exception("Manual governance scan failed.")

        return func.HttpResponse(
            body=json.dumps(
                {
                    "status": "failed",
                    "error": str(error),
                },
                indent=2,
            ),
            status_code=500,
            mimetype="application/json",
        )