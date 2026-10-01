@echo off
setlocal

rem Always run from the repository containing this batch file.
pushd "%~dp0"

set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo ERROR: Virtual environment Python was not found at "%CD%\%PYTHON_EXE%".
    echo Create the virtual environment and install requirements before running tests.
    popd
    exit /b 1
)

rem Use all available CPUs by default. Override with, for example:
rem set PYTEST_WORKERS=3
if not defined PYTEST_WORKERS set "PYTEST_WORKERS=auto"

echo Running pytest with %PYTEST_WORKERS% parallel worker(s)...
"%PYTHON_EXE%" -m pytest -n "%PYTEST_WORKERS%" %*
set "TEST_EXIT_CODE=%ERRORLEVEL%"

popd
exit /b %TEST_EXIT_CODE%
