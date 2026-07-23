from scripts.check_ml_engine_safety import violations


def test_ml_engine_static_safety_gates():
    assert violations() == []
