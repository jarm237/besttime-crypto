from __future__ import annotations

import pytest


@pytest.fixture
def recovery_paths(tmp_path):
    return {
        "evidence": tmp_path / "runtime_evidence.sqlite",
        "reservations": tmp_path / "reservations.db",
        "ledger": tmp_path / "order_fill_ledger.json",
        "positions": tmp_path / "position_projection.json",
    }
