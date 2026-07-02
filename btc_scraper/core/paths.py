from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def build_repo_path(*parts: str | Path) -> Path:
    """Return a path rooted at the repository directory."""
    return REPO_ROOT.joinpath(*[Path(part) for part in parts])


def build_data_path(*parts: str | Path) -> Path:
    """Return a path under the repository data directory."""
    return build_repo_path("data", *parts)


def build_logs_path(*parts: str | Path) -> Path:
    """Return a path under the repository logs directory."""
    return build_repo_path("logs", *parts)


def build_scripts_path(*parts: str | Path) -> Path:
    """Return a path under the repository scripts directory."""
    return build_repo_path("scripts", *parts)
