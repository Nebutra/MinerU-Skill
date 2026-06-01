"""Release-surface checks for package/community skill publishing."""

from __future__ import annotations

import json
import re
from pathlib import Path

import mineru


ROOT = Path(__file__).resolve().parents[1]
TARGET_VERSION = "3.2.0"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_version_surfaces_are_synced_for_release():
    pyproject = _read("pyproject.toml")
    skill = _read("skills/mineru/SKILL.md")
    plugin = json.loads(_read(".claude-plugin/plugin.json"))

    assert mineru.__version__ == TARGET_VERSION
    assert re.search(r'^version = "3\.2\.0"$', pyproject, re.MULTILINE)
    assert re.search(r'^\s+version: "3\.2\.0"$', skill, re.MULTILINE)
    assert plugin["version"] == TARGET_VERSION


def test_release_artifact_packages_community_skill_surfaces():
    release_workflow = _read(".github/workflows/release.yml")

    assert "skills/mineru/" in release_workflow
    assert ".claude-plugin/" in release_workflow


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
