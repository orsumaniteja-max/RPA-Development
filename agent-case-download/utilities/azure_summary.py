"""Generate an Azure DevOps build-summary Markdown file from pytest JUnit XML."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import xml.etree.ElementTree as ET
from urllib.parse import quote


PORTALS = ("cares_connect", "ori_portal", "io_scanner", "carestream", "ddx")


def _result(testcase: ET.Element) -> tuple[str, str]:
    failure = testcase.find("failure")
    error = testcase.find("error")
    skipped = testcase.find("skipped")
    if failure is not None or error is not None:
        detail = failure if failure is not None else error
        message = (detail.get("message") or "Test failed").splitlines()[0]
        return "❌ Failed", message
    if skipped is not None:
        return "⏭️ Skipped", skipped.get("message") or "Skipped"
    return "✅ Passed", ""


def generate_summary(junit_file: Path, output_file: Path) -> None:
    root = ET.parse(junit_file).getroot()
    testcases = root.findall(".//testcase")
    rows = []
    totals = {"passed": 0, "failed": 0, "skipped": 0}

    for testcase in testcases:
        status, detail = _result(testcase)
        if "Failed" in status:
            totals["failed"] += 1
        elif "Skipped" in status:
            totals["skipped"] += 1
        else:
            totals["passed"] += 1
        name = testcase.get("name", "Unknown test").replace("|", "\\|")
        classname = testcase.get("classname", "")
        portal = next((name for name in PORTALS if name in classname.split(".")), None)
        portal_name = portal.replace("_", " ").title() if portal else "Framework"
        duration = f"{float(testcase.get('time', '0')):.2f}s"
        detail = detail.replace("|", "\\|")[:180]
        rows.append(f"| {portal_name} | {name} | {status} | {duration} | {detail} |")

    total = sum(totals.values())
    build_id = os.getenv("BUILD_BUILDID", "")
    collection_uri = os.getenv("SYSTEM_COLLECTIONURI", "")
    project = os.getenv("SYSTEM_TEAMPROJECT", "")
    artifact_url = (
        f"{collection_uri}{quote(project, safe='')}/_build/results?buildId={build_id}"
        "&view=artifacts&type=publishedArtifacts"
    )

    markdown = [
        "# ROE Dental automation results",
        "",
        f"**Total:** {total} &nbsp; ✅ **Passed:** {totals['passed']} &nbsp; "
        f"❌ **Failed:** {totals['failed']} &nbsp; ⏭️ **Skipped:** {totals['skipped']}",
        "",
        "| Portal | Test | Result | Duration | Details |",
        "|---|---|---:|---:|---|",
        *rows,
        "",
        f"[Open the complete HTML report artifact]({artifact_url})",
        "",
        "Artifact path: `roe-dental-test-report/combined-report/index.html`",
    ]
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(markdown), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("junit_file", type=Path)
    parser.add_argument("output_file", type=Path)
    args = parser.parse_args()
    generate_summary(args.junit_file, args.output_file)
