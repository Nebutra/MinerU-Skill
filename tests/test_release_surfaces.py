"""Release-surface checks for package/community skill publishing."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import mineru

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_skill_package  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
TARGET_VERSION = "3.3.1"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_version_surfaces_are_synced_for_release():
    pyproject = _read("pyproject.toml")
    root_skill = _read("SKILL.md")
    skill = _read("skills/mineru/SKILL.md")
    plugin = json.loads(_read(".claude-plugin/plugin.json"))

    assert mineru.__version__ == TARGET_VERSION
    assert re.search(r'^version = "3\.3\.1"$', pyproject, re.MULTILINE)
    assert re.search(r'^\s+version: "3\.3\.1"$', root_skill, re.MULTILINE)
    assert re.search(r'^\s+version: "3\.3\.1"$', skill, re.MULTILINE)
    assert plugin["version"] == TARGET_VERSION


def test_release_artifact_packages_community_skill_surfaces():
    release_workflow = _read(".github/workflows/release.yml")
    publish_workflow = _read(".github/workflows/publish-skill.yml")

    assert "scripts/build_skill_package.py" in release_workflow
    assert "scripts/build_skill_package.py" in publish_workflow
    assert "dist/marketplace-skill" in publish_workflow
    assert ".claude-plugin/" in release_workflow


def test_marketplace_skill_package_is_self_contained(tmp_path):
    package_dir = build_skill_package.build_package(tmp_path / "marketplace-skill")

    assert (package_dir / "SKILL.md").is_file()
    assert (package_dir / "scripts" / "mineru.py").is_file()
    assert (package_dir / "scripts" / "mineru_mcp.py").is_file()
    assert (package_dir / "scripts" / "sinks" / "notion.py").is_file()
    assert (package_dir / "references" / "integrations.md").is_file()
    assert not (package_dir / ".agents").exists()
    assert not list(package_dir.rglob("__pycache__"))


def test_indexed_lobehub_skill_directory_is_self_contained():
    skill_dir = ROOT / "skills" / "mineru"

    assert (skill_dir / "SKILL.md").is_file()
    assert (skill_dir / "scripts" / "mineru.py").is_file()
    assert (skill_dir / "scripts" / "mineru_mcp.py").is_file()
    assert (skill_dir / "scripts" / "sinks" / "notion.py").is_file()
    assert (skill_dir / "references" / "integrations.md").is_file()


def test_python_package_has_build_backend_and_importable_console_targets():
    pyproject = _read("pyproject.toml")

    assert "[build-system]" in pyproject
    assert 'build-backend = "setuptools.build_meta"' in pyproject
    assert (ROOT / "scripts" / "__init__.py").is_file()


def test_release_workflow_builds_and_can_publish_python_distribution():
    release_workflow = _read(".github/workflows/release.yml")

    assert "python -m build" in release_workflow
    assert "pypa/gh-action-pypi-publish" in release_workflow
    assert "PYPI_API_TOKEN" in release_workflow
