"""The landing page offers the same install commands as the README and links to the docs and downloads."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
LANDING = (ROOT / "landing" / "index.html").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_install_commands_on_the_landing_are_the_ones_in_the_readme():
    for command in (
        "brew install rubenamaury/esbi-cli/esbi-cli",
        "uv tool install git+https://github.com/RubenAmaury/esbi-cli",
    ):
        assert command in LANDING and command in README


def test_the_landing_links_to_the_download_and_the_documentation():
    assert "https://github.com/RubenAmaury/esbi-cli/releases/latest" in LANDING
    assert 'href="docs/"' in LANDING
    assert (ROOT / "docs" / "index.md").is_file()
