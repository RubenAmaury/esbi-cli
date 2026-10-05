"""esbi-cli is MIT and depends on no AGPL package. PyMuPDF (AGPL, or a paid Artifex licence) was
replaced by pypdfium2 (BSD-3 and Apache-2.0); this keeps it that way."""

import importlib.metadata
import importlib.util
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent
AGPL_PACKAGES = {"pymupdf", "pymupdf4llm", "pymupdf-layout", "pymupdf-fonts", "mupdf", "fitz"}


def names(requirements) -> set[str]:
    return {
        re.split(r"[<>=!~\[; ]", r, maxsplit=1)[0].lower().replace("_", "-") for r in requirements
    }


def test_no_agpl_package_is_a_dependency():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    declared = names(project["project"]["dependencies"]) | names(
        r
        for group in project.get("dependency-groups", {}).values()
        for r in group
        if isinstance(r, str)
    )
    locked = {p["name"].lower().replace("_", "-") for p in lock["package"]}

    assert not declared & AGPL_PACKAGES
    assert not locked & AGPL_PACKAGES  # nor a dependency of a dependency
    assert "pypdfium2" in declared and "pypdfium2" in locked  # what reads PDFs instead


def test_no_source_file_imports_an_agpl_package():
    pattern = re.compile(r"^\s*(import|from)\s+(pymupdf|fitz)\b", re.M)
    sources = (ROOT / "src").rglob("*.py")

    assert [str(p) for p in sources if pattern.search(p.read_text())] == []


def test_no_installed_distribution_is_agpl_licensed():
    """In the environment that runs the tests: run `uv sync` to drop a package of an older lock."""
    found = []
    for dist in importlib.metadata.distributions():
        meta = dist.metadata
        licence = " ".join([meta.get("License-Expression") or "", meta.get("License") or ""][:2])
        classifiers = " ".join(meta.get_all("Classifier") or [])
        if re.search(r"\bAGPL|Affero", f"{licence} {classifiers}", re.I):
            found.append(meta["Name"])

    assert found == []
    assert importlib.util.find_spec("pymupdf") is None and importlib.util.find_spec("fitz") is None
