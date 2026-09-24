"""Import layering from CLAUDE.md, checked statically.

- Each framework is imported only by the package that owns it, so ``intake.core``
  never imports FastAPI or LiveKit.
- ``intake.api`` and ``intake.agent`` are leaves: no other package imports them.

Ruff bans relative imports (TID252), so every import names its full module.
"""

import ast
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "src" / "intake"
FRAMEWORK_OWNERS = {
    "fastapi": "intake.api",
    "starlette": "intake.api",
    "slowapi": "intake.api",
    "uvicorn": "intake.api",
    "livekit": "intake.agent",
}
LEAF_PACKAGES = ("intake.api", "intake.agent")


def _module_name(path: Path) -> str:
    parts = path.relative_to(PACKAGE_DIR.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _within(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


IMPORTS = {_module_name(path): _imported_modules(path) for path in PACKAGE_DIR.rglob("*.py")}


def test_every_layer_is_scanned():
    assert {"intake.core", "intake.db", "intake.api", "intake.agent"} <= IMPORTS.keys()


@pytest.mark.parametrize(("framework", "owner"), FRAMEWORK_OWNERS.items())
def test_frameworks_stay_in_their_layer(framework: str, owner: str):
    offenders = sorted(
        module
        for module, imports in IMPORTS.items()
        if not _within(module, owner) and any(_within(name, framework) for name in imports)
    )

    assert not offenders, f"only {owner} may import {framework}: {offenders}"


@pytest.mark.parametrize("leaf", LEAF_PACKAGES)
def test_nothing_depends_on_api_or_agent(leaf: str):
    offenders = sorted(
        module
        for module, imports in IMPORTS.items()
        if not _within(module, leaf) and any(_within(name, leaf) for name in imports)
    )

    assert not offenders, f"{leaf} is a leaf, but it is imported by {offenders}"
