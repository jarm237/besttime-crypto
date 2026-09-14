"""Static CI gates for ML production-readiness invariants."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = [
    ROOT / "btc_scraper" / "ml_engine", ROOT / "btc_scraper" / "trading",
    ROOT / "btc_scraper" / "execution", ROOT / "scripts",
]
LOADER = (ROOT / "btc_scraper" / "ml_engine" / "governed_artifact_loader.py").resolve()
FORBIDDEN_CALLS = {"joblib.load", "pickle.load", "torch.load", "PPO.load", "RecurrentPPO.load"}
CRITICAL_FILES = {
    "decision_engine.py", "governed_artifact_loader.py", "model_registry.py",
    "prediction_logger.py", "runtime_calibration.py", "runtime_evidence_store.py",
}


def _call_name(node: ast.Call) -> str:
    parts = []
    current = node.func
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def violations() -> list[str]:
    errors: list[str] = []
    for root in SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if path.parent == ROOT / "scripts" and path.name.startswith(("hmr_", "mc4_", "mc5_", "p7_a5_")):
                continue
            source = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError:
                for line_number, line in enumerate(source.splitlines(), start=1):
                    if any(f"{name}(" in line for name in FORBIDDEN_CALLS) and path.resolve() != LOADER:
                        errors.append(f"{path.relative_to(ROOT)}:{line_number}:direct model deserialization")
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _call_name(node) in FORBIDDEN_CALLS and path.resolve() != LOADER:
                    errors.append(f"{path.relative_to(ROOT)}:{node.lineno}:direct model deserialization")
                if path.name in CRITICAL_FILES and isinstance(node, ast.ExceptHandler):
                    if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                        errors.append(f"{path.relative_to(ROOT)}:{node.lineno}:silent critical exception")
    return errors


if __name__ == "__main__":
    found = violations()
    if found:
        raise SystemExit("\n".join(found))
    print("ML engine safety checks passed")
