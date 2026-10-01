import os
import shutil
import platform
import base64
import uuid
from pathlib import Path
import pytest
import allure
from pytest_html import extras
from dotenv import load_dotenv

from utilities.browser_manager import BrowserManager
from utilities.config_reader import ConfigReader


APPLICATIONS = (
    "ddx", "carestream", "cares_connect", "io_scanner", "ori_portal",
    "axs_straumann",
)
load_dotenv(ConfigReader.PROJECT_ROOT / ".env")


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """Give every pytest invocation a fresh Windows-safe temporary root."""
    if config.option.basetemp is not None:
        return
    run_id = os.environ.get("ROE_PYTEST_RUN_ID")
    if not run_id:
        run_id = uuid.uuid4().hex
        # xdist workers inherit this environment value from the controller.
        os.environ["ROE_PYTEST_RUN_ID"] = run_id
    parallel_temp_root = (
        ConfigReader.PROJECT_ROOT / ".pytest-tmp"
    )
    parallel_temp_root.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(parallel_temp_root / run_id)


def _is_xdist_worker(config) -> bool:
    return hasattr(config, "workerinput")


def _prepare_shared_test_artifacts() -> None:
    """Prepare shared outputs once in the controller before workers start."""
    folders = [
        "reports/allure-results",
        "reports/allure-report",
        "reports/combined-report",
        "reports/logs",
    ]
    folders.extend(
        f"reports/{ConfigReader.get_config(app).get('report_folder', app)}/screenshots"
        for app in APPLICATIONS
    )
    folders.extend(
        f"reports/{ConfigReader.get_config(app).get('report_folder', app)}/results"
        for app in APPLICATIONS
    )

    for folder in folders:
        path = Path(folder)
        if path.name == "results":
            path.mkdir(parents=True, exist_ok=True)
            continue
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    downloads = Path("downloads")
    downloads.mkdir(exist_ok=True)
    for item in downloads.iterdir():
        if item.is_file():
            item.unlink()

    environment_file = Path("reports/allure-results/environment.properties")
    environment_file.write_text(
        "\n".join((
            "Project=ROE Dental Automation",
            "Company=Veltris",
            "Framework=Playwright + Python",
            "Browser=Chromium",
            "Environment=QA",
            f"Operating System={platform.system()}",
            f"Python={platform.python_version()}",
            "",
        )),
        encoding="utf-8",
    )


def pytest_sessionstart(session):
    """Run destructive shared setup only in the controller/main process."""
    if _is_xdist_worker(session.config):
        return
    _prepare_shared_test_artifacts()
    session.config._roe_shared_artifacts_prepared = True


def pytest_addoption(parser):
    group = parser.getgroup("application")
    group.addoption(
        "--application",
        choices=APPLICATIONS,
        help="Run against one application (otherwise inferred from the test path).",
    )
    group.addoption(
        "--app-base-url",
        help="Override the configured base URL for the selected application.",
    )


def _application_for_test(request):
    selected = request.config.getoption("--application")
    if selected:
        return selected

    path_parts = request.node.path.parts
    return next((app for app in APPLICATIONS if app in path_parts), "cares_connect")


def pytest_collection_modifyitems(items):
    """Keep combined portal runs in the configured business priority order."""
    def priority(item):
        application = next((app for app in APPLICATIONS if app in item.path.parts), None)
        if application is None:
            return 999
        return ConfigReader.get_config(application).get("priority", 999)

    items.sort(key=priority)


@pytest.fixture()
def application(request):
    return _application_for_test(request)


@pytest.fixture()
def portal_credentials(application):
    config = ConfigReader.get_config(application)
    username = os.getenv(config.get("username_env", ""))
    password = os.getenv(config.get("password_env", ""))
    if not username or not password:
        pytest.skip(
            f"Credentials for {application} are not configured. Set "
            f"{config.get('username_env')} and {config.get('password_env')}."
        )
    return {"username": username, "password": password}


@pytest.fixture()
def application_report_root(application):
    config = ConfigReader.get_config(application)
    folder_name = config.get("report_folder", application)
    report_root = ConfigReader.PROJECT_ROOT / "reports" / folder_name
    report_root.mkdir(parents=True, exist_ok=True)
    return report_root


# ============================================================
# Framework Initialization
# ============================================================

@pytest.fixture(scope="session", autouse=True)
def framework_setup(request):
    # pytest_sessionstart already prepared shared state in both serial and xdist
    # controller runs. Workers must never delete another worker's artifacts.
    if (
        not _is_xdist_worker(request.config)
        and not getattr(request.config, "_roe_shared_artifacts_prepared", False)
    ):
        _prepare_shared_test_artifacts()
    yield


# ============================================================
# Browser Fixture
# ============================================================

@pytest.fixture()
def page(request):
    application = _application_for_test(request)
    config = ConfigReader.get_config(application)
    base_url = request.config.getoption("--app-base-url") or config.get("base_url")

    if not base_url:
        pytest.skip(f"No base_url configured for {application}.")

    manager = BrowserManager()
    playwright = None
    browser = None
    active_page = None
    try:
        playwright, browser, active_page = manager.launch_browser(
            config["browser"], config["headless"]
        )
        # Register the page before navigation so setup failures are represented
        # correctly in the HTML/Allure reporting hooks.
        request.node.page = active_page
        timeout = config.get("timeout", 30000)
        active_page.set_default_timeout(timeout)
        active_page.set_default_navigation_timeout(timeout)
        active_page.goto(
            base_url,
            wait_until=config.get("navigation_wait_until", "load"),
        )
        yield active_page
    finally:
        # A failed initial navigation happens before fixture yield. Always stop
        # Playwright or every following test reports a false asyncio-loop error.
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()


# ============================================================
# Attach Screenshot on Every Test
# ============================================================

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):

    outcome = yield

    report = outcome.get_result()

    if report.when not in {"setup", "call"} or not report.failed:
        if report.when != "call":
            return

    # Successful calls and call failures get screenshots. Setup failures may
    # already have closed the browser, but must never break report generation.
    if report.when not in {"setup", "call"}:
        return

    page = getattr(item, "page", None)

    if page is None:
        return

    application = next((app for app in APPLICATIONS if app in item.path.parts), "cares_connect")
    app_config = ConfigReader.get_config(application)
    screenshot_folder = (
        ConfigReader.PROJECT_ROOT
        / "reports"
        / app_config.get("report_folder", application)
        / "screenshots"
    )
    screenshot_folder.mkdir(parents=True, exist_ok=True)
    safe_test_name = item.nodeid.replace("/", "_").replace("\\", "_").replace("::", "_")
    screenshot = screenshot_folder / f"{safe_test_name}.png"

    try:
        page.screenshot(path=str(screenshot), full_page=True)
    except Exception:
        return

    # pytest-html embeds these in the single portable HTML report.
    encoded_screenshot = base64.b64encode(screenshot.read_bytes()).decode("ascii")
    report.extras = getattr(report, "extras", []) + [
        extras.png(encoded_screenshot, name="Execution Screenshot"),
        extras.url(page.url, name="Current URL"),
    ]

    if report.failed:

        allure.attach.file(
            str(screenshot),
            name="Failure Screenshot",
            attachment_type=allure.attachment_type.PNG
        )

    else:

        allure.attach.file(
            str(screenshot),
            name="Execution Screenshot",
            attachment_type=allure.attachment_type.PNG
        )


# ============================================================
# Combined HTML Report
# ============================================================

def pytest_html_report_title(report):
    report.title = "ROE Dental Automation - Combined Execution Report"


def pytest_html_results_summary(prefix, summary, postfix, session):
    stats = session.config.pluginmanager.get_plugin("terminalreporter").stats
    passed = len(stats.get("passed", []))
    failed = len(stats.get("failed", [])) + len(stats.get("error", []))
    skipped = len(stats.get("skipped", []))
    total = passed + failed + skipped

    if total:
        passed_degrees = passed / total * 360
        failed_degrees = failed / total * 360
        chart = (
            f"conic-gradient(#2e7d32 0deg {passed_degrees:.2f}deg, "
            f"#c62828 {passed_degrees:.2f}deg "
            f"{passed_degrees + failed_degrees:.2f}deg, "
            f"#ef6c00 {passed_degrees + failed_degrees:.2f}deg 360deg)"
        )
    else:
        chart = "#bdbdbd"

    prefix.append(f"""
        <section style="display:flex;align-items:center;gap:28px;margin:18px 0 28px;">
          <div aria-label="Result pie chart" style="width:150px;height:150px;border-radius:50%;background:{chart};"></div>
          <div style="font-size:15px;line-height:2;">
            <h2 style="margin:0 0 8px;">Combined result summary</h2>
            <div><span style="color:#2e7d32;">&#9679;</span> Passed: <strong>{passed}</strong></div>
            <div><span style="color:#c62828;">&#9679;</span> Failed: <strong>{failed}</strong></div>
            <div><span style="color:#ef6c00;">&#9679;</span> Skipped: <strong>{skipped}</strong></div>
            <div>Total: <strong>{total}</strong></div>
          </div>
        </section>
    """)

# ============================================================
# Attach Page Source on Failure
# ============================================================

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):

    yield

    page = getattr(item, "page", None)
    if page:

        allure.attach(
            page.url,
            "Current URL",
            allure.attachment_type.TEXT
        )


# ============================================================
# Environment Information
# ============================================================

@pytest.fixture(scope="session", autouse=True)
def create_environment_file():
    # Created once by pytest_sessionstart; retained as a compatibility fixture.
    yield


# ============================================================
# Clean Downloads (Optional)
# ============================================================

@pytest.fixture(scope="session", autouse=True)
def clean_downloads():
    # Cleaned once by pytest_sessionstart so xdist workers cannot race.
    yield
