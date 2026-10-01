"""Deterministic account fallback shared by capture and Rx submission."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from typing import Any

LOGGER = logging.getLogger(__name__)


def _portal_identifier(payload: dict[str, Any], namespace: str) -> str | None:
    """Build the configured doctor comparison key from captured portal data."""
    portal = namespace.split(":", 1)[0].lower()
    portal = {"io_scanner": "ioscanner", "ori_portal": "oriportal",
              "cares_connect": "caresconnect"}.get(portal, portal)
    if portal not in {"ioscanner", "oriportal", "carestream", "axs_straumann", "ddx", "caresconnect"}:
        return None
    prescriber = payload.get("customerAccount", {}).get("prescriber") or {}
    if not isinstance(prescriber, dict):
        return None
    contact = prescriber.get("contact") or {}
    if not isinstance(contact, dict):
        contact = {}
    name = prescriber.get("name") or ""
    if not isinstance(name, str):
        name = ""
    name = re.sub(r"\([^)]*\)", "", name).strip()
    name = re.sub(r"^(?:dr|doctor)\.?\s+", "", name, flags=re.I)
    name = re.sub(r"(?:[\s,]+(?:dds|dmd|md)\.?)+$", "", name, flags=re.I)
    if "," in name:
        last, first = name.split(",", 1)
        name = f"{first.strip()} {last.strip()}"
    parts = name.split()
    first = contact.get("first_name") or (parts[0] if parts else "")
    last = contact.get("last_name") or (parts[-1] if len(parts) > 1 else "")
    def component(value: object) -> str:
        return re.sub(r"[^\w-]", "", value).replace("_", "") if isinstance(value, str) else ""
    first, last = component(first), component(last)
    if portal == "oriportal":
        licence = str(prescriber.get("licenceNo") or "").strip()
        if len(parts) == 1 and not contact.get("first_name") and not contact.get("last_name"):
            first, last = "", component(parts[0])
        # Keep all three requested positions, including empty source fields.
        # Missing components do not constitute a unique doctor identification.
        return f"{first}_{last}_{licence}"
    # Do not manufacture names or shared 'unknown' account IDs. Missing fields
    # retain the deterministic digest fallback below so submission can proceed.
    if not first or not last:
        return None
    prefix = f"{first}_{last}"
    if portal == "caresconnect":
        return prefix
    suffix = ""
    if portal == "ioscanner":
        reference = payload.get("reference") or namespace.partition(":")[2]
        match = re.fullmatch(r"(\d+)_\d+", str(reference))
        suffix = match.group(1) if match else str(payload.get("sourceAccountId") or "")
    elif portal == "oriportal":
        suffix = prescriber.get("licenceNo") or ""
    elif portal in {"carestream", "ddx"}:
        suffix = contact.get("email") or ""
        suffix = suffix.strip().casefold() if isinstance(suffix, str) else ""
    elif portal == "axs_straumann":
        suffix = re.sub(r"\D", "", str(contact.get("phone") or ""))
    return f"{prefix}_{str(suffix).strip()}" if suffix else None


def ensure_account_identifier(
    payload: dict[str, Any], namespace: str = "rx-submission"
) -> str:
    """Keep actual account IDs; otherwise encode a versioned source digest.

    A case reference takes priority over mutable clinical details. Otherwise
    canonical JSON makes key ordering irrelevant. Identity output fields are
    excluded so repeated calls do not change the fallback.
    Empty doctor data is supported; callers should retain stable case data or
    supply the portal/case namespace to distinguish otherwise empty cases.
    """
    if not isinstance(payload, dict):
        raise ValueError("Rx submission must be a JSON object")
    account = payload.get("customerAccount")
    if not isinstance(account, dict):
        account = {}
        payload["customerAccount"] = account
    identifier = account.get("id")
    if isinstance(identifier, str) and identifier.strip():
        return identifier
    prescriber = account.get("prescriber")
    identifier = prescriber.get("id") if isinstance(prescriber, dict) else None
    if isinstance(identifier, str) and identifier.strip():
        return identifier
    portal_identifier = _portal_identifier(payload, namespace)
    if portal_identifier:
        account["id"] = portal_identifier
        LOGGER.info("Portal-specific fallback account identifier generated")
        return portal_identifier
    source = json.loads(json.dumps(payload))
    source["customerAccount"].pop("id", None)
    prescriber = source["customerAccount"].get("prescriber")
    if isinstance(prescriber, dict):
        prescriber.pop("id", None)
    reference = payload.get("reference")
    if isinstance(reference, str) and reference.strip():
        source = {"reference": reference.strip()}
    # DDX supplies explicit name components alongside the expanded account
    # contacts. Keep other portals' existing fallback format unchanged.
    contact = prescriber.get("contact") if isinstance(prescriber, dict) else None
    name_prefix = ""
    if isinstance(contact, dict) and "first_name" in contact and "last_name" in contact:
        def clean(value: object) -> str:
            return value.strip().casefold() if isinstance(value, str) else ""

        identity = {
            "first_name": clean(contact.get("first_name")),
            "last_name": clean(contact.get("last_name")),
            "email": clean(contact.get("email")),
            "phone": re.sub(r"\D", "", clean(contact.get("phone"))),
        }
        source = {"case": source, "doctorContact": identity}
        first = re.sub(r"[^\w-]", "", identity["first_name"]).replace("_", "") or "unknown"
        last = re.sub(r"[^\w-]", "", identity["last_name"]).replace("_", "") or "unknown"
        name_prefix = f"{first}_{last}_"
    canonical = json.dumps(
        ["rpa-account-v1", namespace, source], sort_keys=True,
        separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    identifier = base64.urlsafe_b64encode(hashlib.sha256(canonical).digest()).decode("ascii")
    identifier = name_prefix + identifier
    account["id"] = identifier
    LOGGER.info("Fallback account identifier generated")
    return identifier
