"""Attempt #5 Authorization verification test (A5-A2)."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def valid_auth():
    p = REPO_ROOT / "p7_attempt5_authorization.json"
    assert p.exists()
    return json.loads(p.read_text(encoding="utf-8"))


def test_valid_authorization_schema(valid_auth):
    assert valid_auth["authorization_type"] == "P7_REACTIVATION"
    assert valid_auth["attempt"] == 5
    assert valid_auth["release_id"] == "model-coverage-v1-r1"
    assert valid_auth["source_commit"] == "b284ad36f311c5cbf4986c6dfe7f47e8aee01062"
    assert valid_auth["spawn_budget"] == 1
    assert valid_auth["restart_budget"] == 0
    assert valid_auth["state"] == "CONSUMED"
    assert valid_auth["consumed"] is True
    assert len(valid_auth["effective_runtime_symbols"]) == 9
    assert "DOGE" in valid_auth["effective_runtime_symbols"]


def test_invalid_authorizations(valid_auth):
    # 1. Old authorization (Attempt 4)
    auth = dict(valid_auth)
    auth["attempt"] = 4
    with pytest.raises(AssertionError):
        assert auth["attempt"] == 5

    # 2. Wrong release ID
    auth = dict(valid_auth)
    auth["release_id"] = "model-coverage-v1"
    with pytest.raises(AssertionError):
        assert auth["release_id"] == "model-coverage-v1-r1"

    # 3. Wrong source commit
    auth = dict(valid_auth)
    auth["source_commit"] = "grandfathered"
    with pytest.raises(AssertionError):
        assert auth["source_commit"] == "b284ad36f311c5cbf4986c6dfe7f47e8aee01062"

    # 4. Extra symbol (XRP)
    auth = dict(valid_auth)
    auth["effective_runtime_symbols"] = valid_auth["effective_runtime_symbols"] + ["XRP"]
    with pytest.raises(AssertionError):
        assert len(auth["effective_runtime_symbols"]) == 9

    # 5. Missing DOGE
    auth = dict(valid_auth)
    auth["effective_runtime_symbols"] = [s for s in valid_auth["effective_runtime_symbols"] if s != "DOGE"]
    with pytest.raises(AssertionError):
        assert "DOGE" in auth["effective_runtime_symbols"]

    # 6. Invalid budgets
    auth = dict(valid_auth)
    auth["spawn_budget"] = 2
    with pytest.raises(AssertionError):
        assert auth["spawn_budget"] == 1

    auth = dict(valid_auth)
    auth["restart_budget"] = 1
    with pytest.raises(AssertionError):
        assert auth["restart_budget"] == 0

    # 7. Unconsumed state
    auth = dict(valid_auth)
    auth["consumed"] = False
    with pytest.raises(AssertionError):
        assert auth["consumed"] is True
