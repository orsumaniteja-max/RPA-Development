Run the independent fuzzy matching suite from the repository root:

```powershell
.venv\Scripts\python.exe -m pytest -c tests/unit/pytest.fuzzy.ini
```

The configuration bypasses the portal `conftest.py` and its browser dependencies,
report cleanup, and download cleanup. Tests use in-memory synthetic records and
the real `thefuzz` scorer; no credentials, database, browser, or email are needed.
The Python environment needs `pytest` and `thefuzz` from `requirements.txt`.

Add combinations to the parameter table in `test_fuzzy_matching_cases.py` with
doctor name, clinic name, expected name score, expected clinic score, expected
method (`strict`, `fuzzy`, or `None` for no match), and expected confidence.
Scores are on a 0–100 scale. Expected values are fixed regression expectations.

These tests preserve current matching rules: name similarity defaults to a minimum
of 85 for fuzzy matches; clinic similarity contributes to ranking without a minimum
threshold. For name-and-clinic inputs, fuzzy confidence weights name 30 and clinic
20. Strict matches return confidence 100. Identical top candidates require review.

Run the existing doctor matching regression tests alongside this suite:

```powershell
.venv\Scripts\python.exe -m pytest -c tests/unit/pytest.fuzzy.ini tests/unit/test_fuzzy_matching_cases.py tests/unit/test_doctor_fuzzy_matching.py
```
