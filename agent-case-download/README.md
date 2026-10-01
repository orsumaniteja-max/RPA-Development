# CARES Connect Automation Framework

> This repository now hosts page objects and tests for DDX, Carestream,
> CARES Connect, IO Scanner, and ORI Portal. Shared browser, configuration,
> reporting, and page interaction code remains at framework level.

## Running tests by application

### Prerequisites

1. Install Python 3.12 or later.
2. Install dependencies and the Playwright browser.
3. Copy `.env.example` to `.env` and populate all portal credentials.
4. Confirm the centralized portal URLs under `applications` in
   `config/config.yaml` are reachable from the execution environment.

```powershell
Copy-Item .env.example .env
python -m pip install -r requirements.txt
python -m playwright install chromium
```

The configured application endpoints are:

| Priority | Application | URL |
|---:|---|---|
| 1 | CARES Connect | `https://caresconnect.straumann.com/stmn-dhs-webui/` |
| 2 | ORI Portal | `https://oriportal.com/cases` |
| 3 | IO Scanner | `https://scanner.ioscanner.com/login` |
| 4 | Carestream | `https://csdentalconnect.com/` |
| 5 | DDX | `https://roedental.ddxdental.com/lab` |

Run commands from the project root. `--app-base-url` remains available for a
temporary endpoint override without changing the centralized configuration.

```powershell
# One application
python -m pytest tests/ddx --application=ddx
python -m pytest tests/carestream --application=carestream
python -m pytest tests/cares_connect --application=cares_connect
python -m pytest tests/io_scanner --application=io_scanner
python -m pytest tests/ori_portal --application=ori_portal

# One suite or test module
python -m pytest tests/cares_connect/smoke --application=cares_connect
python -m pytest tests/cares_connect/smoke/test_capture_case_details.py --application=cares_connect

# All applications (the fixture infers the application from each test path)
python -m pytest

# Fast, offline import/collection validation
python -m compileall -q pages services utilities tests conftest.py
python -m pytest --collect-only -q
```

Portal credentials are loaded dynamically from `.env`; use `.env.example` as
the template. The real `.env` is ignored by Git. When all portal tests are run
together, collection follows the priorities declared in `config/config.yaml`.

Business outputs and execution screenshots are separated automatically:

```text
reports/
├── caresconnect/
├── oriportal/
├── ioscanner/
├── carestream/
├── ddx/
└── allure-results/     # aggregate Allure input for the complete run
```
---

# Project Overview

This project is an Enterprise Automation Framework developed using **Python + Playwright + Pytest** for automating the **Straumann CARES Connect** application.

The framework follows a **Hybrid Architecture** combining:

- Page Object Model (POM)
- Component Object Model
- Service Layer
- Utility Layer
- Fixtures
- Data Driven Testing
- API Integration
- Database Validation
- CI/CD Ready

The framework is scalable, reusable, and designed for enterprise automation projects.

---

# Tech Stack

| Technology | Version |
|------------|---------|
| Python | 3.12+ |
| Playwright | Latest |
| Pytest | Latest |
| Allure | Latest |
| Loguru | Latest |
| Faker | Latest |
| Requests | Latest |
| Openpyxl | Latest |
| Pandas | Latest |
| PyYAML | Latest |

---

# Project Structure

```
CARES_CONNECT_AUTOMATION

│
├── config
│      config.yaml
│      environments.yaml
│
├── pages
│      base_page.py
│      login_page.py
│      dashboard_page.py
│      track_page.py
│      order_page.py
│
├── components
│      header_component.py
│      menu_component.py
│      order_component.py
│      search_component.py
│
├── services
│      login_service.py
│      order_service.py
│      api_service.py
│
├── tests
│      smoke
│      sanity
│      regression
│      api
│      database
│
├── fixtures
│      conftest.py
│
├── utilities
│      browser_manager.py
│      logger.py
│      waits.py
│      assertions.py
│      excel_reader.py
│      json_reader.py
│      database.py
│      screenshot.py
│      file_utils.py
│      random_generator.py
│
├── testdata
│      users.json
│      orders.json
│      excel_data.xlsx
│
├── reports
│      allure-results
│      html-report
│      screenshots
│      videos
│      traces
│
├── logs
│
├── requirements.txt
├── pytest.ini
├── .env
└── README.md
```

---

# Framework Design

```
Test Case

↓

Service Layer

↓

Page Objects

↓

Reusable Components

↓

Playwright Browser

↓

Application
```

---

# Features

- Cross Browser Support
- Chromium
- Firefox
- WebKit
- Headless Execution
- Parallel Execution
- Automatic Screenshots
- Video Recording
- Trace Viewer
- HTML Reports
- Allure Reports
- Logging
- Retry Mechanism
- Environment Management
- Test Data Management
- API Validation
- Database Validation
- CI/CD Integration

---

# Installation

## Clone Repository

```bash
git clone https://github.com/your-org/cares-connect-automation.git
```

---

## Navigate to Project

```bash
cd cares-connect-automation
```

---

## Create Virtual Environment

Windows

```bash
python -m venv venv
```

Activate

```bash
venv\Scripts\activate
```

Linux / Mac

```bash
source venv/bin/activate
```

---

## Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Install Playwright Browsers

```bash
playwright install
```

---

## Verify Installation

```bash
pytest --version
```

```bash
playwright --version
```

---

# requirements.txt

```
playwright
pytest
pytest-playwright
pytest-html
pytest-xdist
pytest-rerunfailures
allure-pytest
requests
openpyxl
pandas
python-dotenv
loguru
Faker
PyYAML
jsonschema
sqlalchemy
pyodbc
```

---

# Running Tests

## Execute All Tests

```bash
pytest
```

---

## Smoke Tests

```bash
pytest tests/smoke
```

---

## Regression

```bash
pytest tests/regression
```

---

## Specific Test

```bash
pytest tests/regression/test_login.py
```

---

## Parallel Execution

```bash
pytest -n auto
```

---

## Headed Mode

```bash
pytest --headed
```

---

## Browser Selection

Chromium

```bash
pytest --browser chromium
```

Firefox

```bash
pytest --browser firefox
```

Webkit

```bash
pytest --browser webkit
```

---

# Reporting

## HTML Report

```bash
pytest --html=reports/report.html
```

---

## Allure Report

Run Tests

```bash
pytest --alluredir=reports/allure-results
```

Generate Report

```bash
allure serve reports/allure-results
```

---

# Logging

Logs are automatically generated inside

```
logs/
```

Centralized example

```
INFO
PASS
FAIL
ERROR
WARNING
```

---

# Screenshots

Failure screenshots

```
reports/screenshots
```

---

# Videos

Videos are available in

```
reports/videos
```

---

# Playwright Trace

```
reports/traces
```

Open Trace

```bash
playwright show-trace trace.zip
```

---

# Configuration

```
config/config.yaml
```

Example

```yaml
browser: chromium
headless: false
timeout: 30000
applications:
  cares_connect:
    base_url: https://caresconnect.straumann.com/stmn-dhs-webui/
  ori_portal:
    base_url: https://oriportal.com/cases
  io_scanner:
    base_url: https://scanner.ioscanner.com/login
  carestream:
    base_url: https://csdentalconnect.com/
  ddx:
    base_url: https://roedental.ddxdental.com/lab
```

---

# Environment Variables

Create

```
.env
```

Example

```
CARES_CONNECT_USERNAME=xxxx
CARES_CONNECT_PASSWORD=xxxx
ORI_PORTAL_USERNAME=xxxx
ORI_PORTAL_PASSWORD=xxxx
# Continue with the names declared in .env.example.
```

---

# Best Practices

- Do not use time.sleep()
- Use Playwright auto waits
- Keep tests independent
- Store locators only inside Page Objects
- Use reusable Components
- Keep assertions inside Tests
- Never hardcode credentials
- Keep reusable methods inside Utilities
- Use API for setup whenever possible
- Capture screenshots only on failures
- Enable traces for failed tests

---

# Folder Responsibilities

| Folder | Responsibility |
|----------|----------------|
| pages | UI actions |
| components | Reusable UI blocks |
| services | Business workflows |
| utilities | Generic helper methods |
| tests | Test scenarios |
| config | Environment configuration |
| testdata | External data |
| fixtures | Browser lifecycle |
| reports | Reports |
| logs | Execution logs |

---

# Automation Scope

The framework automates

- Login
- Logout
- Order Search
- Advanced Search
- Refresh
- Expand Orders
- Collapse Orders
- Change Order Status
- Validate Client Details
- Validate Patient Details
- Validate Dentist Details
- Validate Due Date
- Validate Material
- Validate Scan Details
- Bulk Order Actions
- API Validation
- Database Validation

---

# CI/CD

Supports

- Azure DevOps
- Jenkins
- GitHub Actions

Pipeline

```
Checkout

↓

Install Dependencies

↓

Install Playwright

↓

Run Tests

↓

Generate Reports

↓

Publish Reports

↓

Email Notification
```

---

# Coding Standards

- PEP8
- Black Formatter
- Ruff
- Flake8

---

# Future Enhancements

- Docker Support
- Kubernetes Execution
- BrowserStack Integration
- LambdaTest Integration
- AI-assisted Test Generation
- Self-healing Locators
- Slack Notifications
- Teams Notifications
- Email Reports

---

# Author

**Sai Kodala**
# RPA database tracking

`run_rpa.py` in `capture_and_upload` mode uploads pending saved results first.
For example, `{"application":"carestream","records":1,"mode":"capture_and_upload"}`
submits at most one pending Carestream case. If a saved pending case is available,
it does not launch the portal or load the doctor catalog. If saved results cannot
fill the requested count, it captures only the remaining number of new cases.
Cases already downloaded do not consume that new-case limit. Uploads with an
uncertain outcome are left for review rather than retried automatically.

Normal capture runs for all six applications traverse every results page until
Next is unavailable or disabled, with no default 50-record cutoff. Existing
downloads are skipped while navigation continues to subsequent pages. The
current portal filters still determine which cases are included.
CARES capture leaves status unfiltered by default and follows the unlabeled
Next arrow beside the `Displaying ... out of ...` counter through the final
range. A status filter can still be supplied explicitly. Explicit
`max_cases` and `max_new_cases` limits remain available for bounded callers.

Normal capture runs synchronize new downloads and preserved local history to
Azure SQL. CARES Connect case references, output filenames, and tracking IDs
include the portal's case date/time as `CaseID_YYYYMMDD-HHMMSS`, because different
records can share a case name. Date-only values use `000000` for the time;
missing or unsupported dates stop capture instead of merging records. Existing
undated files are preserved, and those cases may be captured once again under
their dated IDs. This does not change the prescriber's ID.

Tracking uses
Azure SQL `dbo.RpaApplication` and `dbo.RpaDownloadedCase`, using the existing
`AZURE_SQL_SERVER`, `AZURE_SQL_DATABASE`, `AZURE_SQL_USERNAME`, and
`AZURE_SQL_PASSWORD` environment settings. SQL Server generates the primary
keys; each case uses its application's SQL ID as `ApplicationId`. Inserts check
the `(ApplicationId, PrescriptionId)` pair under transaction locks, preserving
existing records and their `CreatedAt` values.

To backfill all portals without opening browsers or uploading cases, run:

```powershell
python -m utilities.sync_rpa_case_history
```

SQLite remains the local history/CSV source. SQL failures are reported and
retained local history is retried on the next run. Explicit `database_path`
callers remain local-only unless a `sql_tracker` is supplied (for isolated tests).
