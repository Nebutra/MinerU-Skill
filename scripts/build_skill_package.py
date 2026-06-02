#!/usr/bin/env python3
"""Build a self-contained marketplace skill directory."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dist" / "marketplace-skill"

PACKAGE_PATHS = [
    "SKILL.md",
    "scripts",
    "references",
    "LICENSE",
    "README.md",
    "README_CN.md",
]

EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_FILES = {"build_skill_package.py"}


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree(src: Path, dst: Path) -> None:
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if path.name in EXCLUDED_FILES:
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        _copy_file(path, target)


def build_package(output: Path = DEFAULT_OUTPUT) -> Path:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    for rel_path in PACKAGE_PATHS:
        src = ROOT / rel_path
        dst = output / rel_path
        if src.is_dir():
            _copy_tree(src, dst)
        else:
            _copy_file(src, dst)

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a self-contained marketplace skill.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT, help="Output directory")
    args = parser.parse_args()

    output = build_package(args.out)
    file_count = sum(1 for path in output.rglob("*") if path.is_file())
    print(f"Built marketplace skill package at {output} ({file_count} files)")


if __name__ == "__main__":
    main()
