"""esbi-cli: LLM-maintained Obsidian wiki worker."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("esbi-cli")  # pyproject.toml is the one place the version is written
except PackageNotFoundError:  # running from a bare source tree
    __version__ = "0+unknown"
