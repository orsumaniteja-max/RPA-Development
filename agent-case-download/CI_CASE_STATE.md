# Persistent case downloads in CI

## Optional Labtrac uploads

In **Run pipeline**, choose an application (or `all`) and set
`labtracRecordsPerApplication`:

- `0` (default, including scheduled runs): capture only; no Labtrac uploads or
  Labtrac secret loading.
- Any positive whole number: after successful capture, attempt at most that many
  pending saved cases per selected application. For example, `carestream` with `5`
  allows up to five Carestream uploads; `all` with `1` allows up to six uploads,
  one per portal. Negative and fractional counts are rejected.

For uploads, the configured Key Vault must contain `LABTRAC-CLIENT-SECRET` and
the pipeline service connection must have access to it. The client uses the
Labtrac account/endpoints configured as defaults in `LabtracSettings`.
The API user must be associated with each submitted customer account.
CI upload selection is independent of `config/rpa_input.json`.

Before an opted-in upload, CI resolves the captured doctor name against
`dbo.Doctor` and sends the unique `AccountId` as both `customerAccount.id` and
`customerAccount.prescriber.id`. A missing or ambiguous full-name match is
marked `needs_review` without calling Labtrac. Similar names are not treated as
the same doctor: for example, Dr. Nanette Mick (`MICKN`) cannot be used for
Dr. Nanette Tertel.

Uploaded and uncertain submissions are skipped using the restored upload history.
An empty pending queue is reported without opening another browser. Failed or
uncertain submissions make the upload step fail; other selected portals are still
processed. History is saved afterward even when uploading fails. Existing local
upload history must be imported with the seed to prevent resubmitting local uploads.

The pipeline restores `rpa-case-state/state.zip` before portal capture and publishes
a cumulative replacement afterward, including when portal tests fail. It contains
`reports/<portal>/results`, the SQLite tracking database, and Labtrac upload history.
The combined HTML report remains a separate artifact. Generated case files do not
need to be committed to Git.

## First run: include cases already downloaded locally

1. Stop local capture/upload while creating the seed.
2. Run from this project folder:

   ```powershell
   .\.venv\Scripts\python.exe utilities/ci_case_state.py pack --metadata-only --archive data/ci-case-state-seed.zip
   ```

3. Upload `data/ci-case-state-seed.zip` to Azure DevOps **Pipelines > Library >
   Secure files** and authorize this pipeline to read it.
4. Queue the updated pipeline with `caseStateSeedFile` set to that Secure File's
   name. Set `allowEmptyCaseState` false if startup must require saved history.

This field is not the pipeline YAML path. For example, enter
`ci-case-state-seed.zip`, never `azure-pipelines.yml`. Leave the default `none`
when restoring a previous pipeline artifact without importing a Secure File.

The compact seed includes JSON case details and tracking/upload history, but omits
PDFs, screenshots and text evidence to fit the Secure File size limit. Keep that
evidence locally. Normal CI snapshots include all result files. The seed is used
only when no previous state artifact exists; future runs restore the cumulative
artifact. Check the generated archive size against Azure's Secure File limit
before uploading. Do not put the seed or patient data in Git.

First-run initialization is enabled by default (`allowEmptyCaseState=true`,
`caseStateSeedFile=none`). When no previous artifact or seed exists, CI starts
with the checkout's available state and publishes cumulative history afterward.
Subsequent runs restore that artifact automatically. Local-only result files and
upload history are not imported by this option; supply a seed ZIP to preserve them
and avoid downloading those cases again. SQL tracking alone does not restore files.
Set `allowEmptyCaseState=false` to require saved history before capture.
An old HTML report alone cannot initialize download history. If a prior capture
started but could not publish its artifact, `allowEmptyCaseState=true` lets a new
run initialize fresh state and records a warning in the log. This is needed when
the hosted agent workspace is no longer recoverable. Set it to `false` to keep
the stricter block. Overlapping active or queued runs always block startup.

## Azure permissions and retention

History lookup prints progress immediately and checks artifact availability in
batches of eight, evaluating the results newest first. Each API request has a
15-second socket timeout; no new requests start after a 120-second lookup budget.
The pipeline also enforces a three-minute task limit. Repeated pagination tokens
fail explicitly instead of looping. A lookup failure never means empty history:
capture remains blocked until history can be verified.

The pipeline's Build Service identity needs **View builds**, access to its pipeline
artifacts, and **Retain indefinitely** permission. `System.AccessToken` is passed
only to history discovery/retention steps. Authentication errors stop capture.
Each prepared run receives a retention lease through `POST retention/leases`,
using numeric pipeline/run IDs and the requesting user's ID. The lease lasts
36,501 days (Azure displays leases longer than 100 years as retained forever),
so automated retention cannot erase
the only available history. Periodically remove older retained runs only after
verifying a newer cumulative `rpa-case-state` artifact and keeping a backup.

History is shared across applications and branches of this pipeline definition.
Do not run a separate pipeline definition or local automation against the same
cases concurrently: those executions do not participate in this CI guard. An
earlier queued/running build blocks a later build; rerun after it completes.

If a run starts capture but has no published state (for example, agent loss or
forced cancellation), the next run stops rather than silently using older
history. Recover the case files and publish the missing artifact before retrying.
Do not remove the `rpa-capture-started` tag to bypass this protection.

## Runtime behavior

Known cases skip downloads and exports. ORI checks the identifier before reading
the full case details or extracting prescription data. DDX no longer recaptures
known cases solely because their contact fields are empty. Some portals still
need to open the case to read its identifier; listing, login, Docker setup and
artifact transfer still take time. Existing portal scan limits remain in effect.

The first seed imports local history at one point in time. Later local downloads
are not automatically synchronized into CI. Use CI as the sole capture runner
after migration, or introduce shared storage before running both environments.

Reference: [Azure Pipeline artifact downloads](https://learn.microsoft.com/en-us/azure/devops/pipelines/tasks/reference/download-pipeline-artifact-v2?view=azure-pipelines).
# Azure SQL synchronization

After restoring case state, CI runs `python -u -m utilities.sync_rpa_case_history`
inside the same Docker image, mounting the restored `data` and `reports` folders.
This backfills all portals into `dbo.RpaApplication` and `dbo.RpaDownloadedCase`,
even when capture selects only one portal. Each new download also synchronizes
through the shared tracker. Existing application/prescription pairs are preserved.

Both steps receive the four `AZURE_SQL_*` settings from the existing Key Vault
secrets. A synchronization failure fails the step rather than silently leaving SQL
behind. Local state is still saved by the existing always-run artifact steps and
is retried on the next run. The build agent must be able to reach Azure SQL.
