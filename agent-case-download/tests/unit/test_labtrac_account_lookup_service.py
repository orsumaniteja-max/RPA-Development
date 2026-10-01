import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services.labtrac_account_lookup_service import (
    LabtracAccountLookupError, LabtracAccountLookupService,
)


def test_exact_normalized_name_returns_database_account_id(monkeypatch):
    connection = Mock()
    connection.cursor.return_value.fetchall.return_value = [
        {"AccountId": "MICKN", "AccountName": "Dr. Nanette Mick"},
        {"AccountId": "OTHER", "AccountName": "Dr. Nanette Other"},
    ]
    connect = Mock(return_value=connection)
    monkeypatch.setitem(sys.modules, "pymssql", SimpleNamespace(connect=connect))
    for key in ("SERVER", "DATABASE", "USERNAME", "PASSWORD"):
        monkeypatch.setenv("AZURE_SQL_" + key, "test")
    assert LabtracAccountLookupService().resolve("Nanette Mick") == "MICKN"
    query, values = connection.cursor.return_value.execute.call_args.args
    assert "AccountId" in query and values == ("%mick%",)
    connection.close.assert_called_once()


def test_similar_but_different_doctor_name_never_selects_account(monkeypatch):
    connection = Mock()
    connection.cursor.return_value.fetchall.return_value = [
        {"AccountId": "MICKN", "AccountName": "Dr. Nanette Mick"},
    ]
    monkeypatch.setitem(sys.modules, "pymssql", SimpleNamespace(connect=Mock(return_value=connection)))
    for key in ("SERVER", "DATABASE", "USERNAME", "PASSWORD"):
        monkeypatch.setenv("AZURE_SQL_" + key, "test")
    with pytest.raises(LabtracAccountLookupError, match="no unique"):
        LabtracAccountLookupService().resolve("Dr. Nanette Tertel")
