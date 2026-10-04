"""What an installed copy needs must be inside the package, not read from the project checkout."""

from pathlib import Path

import esbi_cli
from esbi_cli import init

PACKAGE = Path(esbi_cli.__file__).parent


def test_the_starter_files_ship_inside_the_package():
    assert (PACKAGE / "templates" / "config.example.toml").is_file()
    assert (PACKAGE / "templates" / "SCHEMA.md").is_file()
    assert init.EXAMPLE_CONFIG == PACKAGE / "templates" / "config.example.toml"


def test_the_example_config_at_the_project_root_is_the_packaged_one_not_a_second_copy():
    root_copy = PACKAGE.parents[1] / "config.example.toml"
    if root_copy.exists():  # a source checkout; an installed copy has no project root
        assert root_copy.resolve() == init.EXAMPLE_CONFIG.resolve()


def test_the_version_comes_from_the_package_metadata():
    from importlib.metadata import version

    assert esbi_cli.__version__ == version("esbi-cli")
