"""Preserve case outputs between Azure runs without committing patient files."""

from __future__ import annotations

import argparse
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import time
from urllib.parse import urlencode, quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile, ZIP_DEFLATED


ARTIFACT = "rpa-case-state"
CAPTURE_TAG = "rpa-capture-started"
MANIFEST = "case-state.json"
DATA_FILES = {"rpa_case_tracking.db", "rpa_case_tracking.csv"}
RETENTION_DAYS = 36501  # Azure displays leases longer than 100 years as forever.


def allowed(name):
    parts = PurePosixPath(name).parts
    if "\\" in name or ":" in name or ".." in parts or name.startswith("/"):
        return False
    return (
        len(parts) == 2 and parts[0] == "data" and parts[1] in DATA_FILES
        or len(parts) >= 4 and parts[0] == "reports" and parts[2] == "results"
        or len(parts) == 3 and parts[:2] == ("reports", "labtrac")
        and parts[2] in {"upload_history.csv", "upload_history.initialized"}
    )


def pack(root, destination, metadata_only=False):
    root, destination = Path(root).resolve(), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(p for directory in (root / "reports", root / "data")
                   if directory.exists() for p in directory.rglob("*")
                   if p.is_file() and not p.is_symlink()
                   and allowed(p.relative_to(root).as_posix()))
    if metadata_only:
        files = [p for p in files if p.suffix not in {".png", ".pdf", ".txt", ".jpg", ".zip"}]
    with tempfile.TemporaryDirectory() as temporary, ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST, json.dumps({"version": 1, "metadataOnly": metadata_only}))
        for path in files:
            name = path.relative_to(root).as_posix()
            if path.suffix == ".db":
                backup = Path(temporary) / path.name
                with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as target:
                    source.backup(target)
                archive.write(backup, name)
            else:
                try:
                    archive.write(path, name)
                except PermissionError as error:
                    raise RuntimeError(
                        f"Cannot read case-state file {name}. Ensure Docker bind-mounted "
                        "reports and data are owned by the build-agent user before packing."
                    ) from error
    print(f"Saved {len(files)} case-state files ({destination.stat().st_size} bytes)")


def restore(archive_path, root, overwrite=True):
    root = Path(root).resolve()
    with ZipFile(archive_path) as archive:
        if json.loads(archive.read(MANIFEST)).get("version") != 1:
            raise ValueError("Unsupported case-state archive")
        members = [item for item in archive.infolist() if item.filename != MANIFEST]
        # Validate the entire archive before writing any files.
        for item in members:
            destination = (root / item.filename).resolve()
            if not allowed(item.filename) or not destination.is_relative_to(root):
                raise ValueError("Unexpected path in case-state archive")
        for item in members:
            destination = root / item.filename
            if not overwrite and destination.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
    print(f"Restored {len(members)} case-state files")


class AzureBuilds:
    def __init__(self):
        self.base = (os.environ["SYSTEM_COLLECTIONURI"].rstrip("/") + "/"
                     + quote(os.environ["SYSTEM_TEAMPROJECT"], safe="") + "/_apis/build/")
        self.token = os.environ["SYSTEM_ACCESSTOKEN"]
        if not self.token or self.token.startswith("$("):
            raise RuntimeError("System.AccessToken is required to restore case history")
        self.deadline = time.monotonic() + 120

    def request(self, path, query=None, body=None, method=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Case history lookup exceeded 120 seconds; history was not verified. "
                               "Check Azure DevOps connectivity and retry a new run.")
        query = {"api-version": "7.1", **(query or {})}
        request = Request(self.base + path + "?" + urlencode(query),
                          data=json.dumps(body).encode() if body is not None else None,
                          method=method,
                          headers={"Authorization": "Bearer " + self.token,
                                   "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=min(15, remaining)) as response:
                return json.load(response), response.headers.get("x-ms-continuationtoken")
        except HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw).get("message", error.reason)
            except (ValueError, AttributeError):
                detail = error.reason
            detail = str(detail).replace(self.token, "[REDACTED]")[:1500]
            raise RuntimeError(
                f"Azure DevOps {request.get_method()} {path} failed "
                f"(HTTP {error.code}): {detail}"
            ) from None

    def retain(self, build_id, definition_id, owner_id):
        """Protect a running build using the pipeline retention-lease API."""
        print(f"Protecting case history for build {build_id} with a retention lease...", flush=True)
        self.request("retention/leases", method="POST", body=[{
            "daysValid": RETENTION_DAYS,
            "definitionId": int(definition_id),
            "ownerId": "User:" + owner_id,
            "protectPipeline": False,
            "runId": int(build_id),
        }])

    def builds(self):
        query = {"definitions": os.environ["SYSTEM_DEFINITIONID"],
                 "queryOrder": "queueTimeDescending", "$top": 100}
        result = []
        seen_tokens = set()
        while True:
            print(f"Reading pipeline build history ({len(result)} builds loaded)...", flush=True)
            page, continuation = self.request("builds", query)
            result.extend(page["value"])
            if not continuation:
                return result
            if continuation in seen_tokens:
                raise RuntimeError("Azure DevOps repeated a history continuation token; "
                                   "stopping instead of looping indefinitely.")
            seen_tokens.add(continuation)
            query["continuationToken"] = continuation

    def artifacts(self, build_id):
        result, _ = self.request(f"builds/{build_id}/artifacts")
        return result["value"]


def select_build(api, current_id, job_attempt=1, allow_missing_capture_state=False):
    """Fail rather than capture concurrently or silently lose newer history."""
    if job_attempt != 1:
        raise RuntimeError("Queue a new pipeline run instead of retrying this job; "
                           "case-state artifacts are immutable within a build.")
    print("Checking prior runs and saved case history...", flush=True)
    previous = sorted((b for b in api.builds() if b["id"] < current_id),
                      key=lambda b: b["id"], reverse=True)
    if any(b["status"] != "completed" for b in previous):
        raise RuntimeError("An earlier run is still active/queued. Retry after it finishes.")
    # Fetch small batches concurrently, but evaluate strictly newest first.
    # Completion order must never allow older state to bypass a lost capture.
    with ThreadPoolExecutor(max_workers=8) as executor:
        for offset in range(0, len(previous), 8):
            batch = previous[offset:offset + 8]
            print(f"Checking case-state artifacts: builds {batch[0]['id']} through "
                  f"{batch[-1]['id']} ({offset}/{len(previous)} checked)", flush=True)
            pending = [executor.submit(api.artifacts, build["id"]) for build in batch]
            for build, future in zip(batch, pending):
                if any(a["name"] == ARTIFACT for a in future.result()):
                    print(f"Found saved case history in build {build['id']}", flush=True)
                    return build["id"]
                if CAPTURE_TAG in build.get("tags", []):
                    if allow_missing_capture_state:
                        print(f"Build {build['id']} started capture but saved no state; "
                              "starting with fresh state by request.", flush=True)
                        # Older artifacts predate the lost capture and therefore
                        # cannot safely represent the current history.
                        return None
                    raise RuntimeError(f"Build {build['id']} started capture but saved no state. "
                                       "Recover its results before capturing again.")
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("pack", "restore", "select", "retain"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--merge", action="store_true")
    args = parser.parse_args()
    if args.action in {"pack", "restore"} and args.archive is None:
        parser.error("--archive is required")
    if args.action == "pack":
        pack(args.root, args.archive, args.metadata_only)
    elif args.action == "restore":
        restore(args.archive, args.root, overwrite=not args.merge)
    elif args.action == "select":
        build_id = select_build(AzureBuilds(), int(os.environ["BUILD_BUILDID"]),
                                int(os.getenv("SYSTEM_JOBATTEMPT", "1")),
                                os.getenv("ALLOW_EMPTY_CASE_STATE", "").lower()
                                in {"1", "true", "yes", "on"})
        print(f"##vso[task.setvariable variable=caseStateBuild]{build_id or ''}")
        print(f"Case history source: {build_id or 'no previous state artifact'}")
    else:
        AzureBuilds().retain(os.environ["BUILD_BUILDID"], os.environ["SYSTEM_DEFINITIONID"],
                             os.environ["BUILD_REQUESTEDFORID"])
        print("Protected this run's case history with a long-term retention lease")


if __name__ == "__main__":
    main()
