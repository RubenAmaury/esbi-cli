"""Which way esbi-cli was installed decides how it is updated. Paths are injected: no test looks at
the real environment."""

import sys
from pathlib import Path

import pytest

from esbi_cli.update import (
    install_method,
    manual_message,
    pinned_source,
    upgrade_command,
)

SITE = Path("/anywhere/lib/python3.13/site-packages/esbi_cli")
CHECKOUT = Path("/code/esbi-cli/src/esbi_cli")


@pytest.mark.parametrize(
    "prefix",
    [
        "/opt/homebrew/Cellar/esbi-cli/0.1.0/libexec",  # Apple Silicon
        "/usr/local/Cellar/esbi-cli/0.1.0/libexec",  # Intel
        "/home/linuxbrew/.linuxbrew/Cellar/esbi-cli/0.1.0/libexec",
        "/opt/homebrew/opt/esbi-cli/libexec",  # the stable symlink Homebrew keeps
    ],
)
def test_a_homebrew_prefix_is_recognised(prefix):
    assert install_method(Path(prefix), SITE) == "brew"


def test_a_uv_tool_is_recognised_by_its_receipt_or_its_folder(tmp_path):
    (tmp_path / "uv-receipt.toml").write_text("[tool]\n")
    assert install_method(tmp_path, SITE) == "uv-tool"
    assert install_method(Path("/h/.local/share/uv/tools/esbi-cli"), SITE) == "uv-tool"


def test_a_pipx_venv_is_recognised(tmp_path):
    assert install_method(Path("/h/.local/pipx/venvs/esbi-cli"), SITE) == "pipx"
    (tmp_path / "pipx_metadata.json").write_text("{}")
    assert install_method(tmp_path, SITE) == "pipx"


def test_a_source_checkout_is_editable_even_inside_a_uv_tool(tmp_path):
    (tmp_path / "code").mkdir()
    (tmp_path / "code" / "pyproject.toml").write_text("[project]\n")
    package = tmp_path / "code" / "src" / "esbi_cli"
    prefix = tmp_path / "uv" / "tools" / "esbi-cli"
    prefix.mkdir(parents=True)
    (prefix / "uv-receipt.toml").write_text("[tool]\n")  # `uv tool install --editable .`

    assert install_method(prefix, package) == "editable"


def test_a_package_in_site_packages_of_some_other_environment_is_pip():
    assert install_method(Path("/home/me/venvs/work"), SITE) == "pip"


def test_a_layout_nobody_expected_is_unknown():
    assert install_method(Path("/somewhere"), Path("/somewhere/else/esbi_cli")) == "unknown"
    assert install_method(Path("/somewhere"), CHECKOUT) == "unknown"  # no pyproject.toml there


def test_each_method_has_its_exact_command_as_a_list_never_a_shell_string():
    assert upgrade_command("brew", "0.2.0") == ["brew", "upgrade", "rubenamaury/esbi-cli/esbi-cli"]
    assert upgrade_command("uv-tool", "0.2.0") == ["uv", "tool", "upgrade", "esbi-cli"]
    assert upgrade_command("pipx", "0.2.0") == ["pipx", "upgrade", "esbi-cli"]
    assert upgrade_command("editable", "0.2.0") is None
    assert upgrade_command("unknown", "0.2.0") is None


def test_pip_installs_the_release_tag_from_github_not_a_name_from_an_index():
    argv = upgrade_command("pip", "0.2.0")

    assert argv[:5] == [sys.executable, "-m", "pip", "install", "--upgrade"]
    assert argv[5:] == ["https://github.com/RubenAmaury/esbi-cli/archive/refs/tags/v0.2.0.zip"]


def test_the_tool_that_runs_the_command_is_never_taken_from_the_version_text():
    # a tag that did not pass the release check cannot become part of a command
    with pytest.raises(ValueError):
        upgrade_command("pip", "0.2.0; rm -rf ~")


def write_receipt(prefix: Path, requirement: str) -> Path:
    prefix.mkdir(exist_ok=True)
    (prefix / "uv-receipt.toml").write_text(
        f"[tool]\nrequirements = [{requirement}]\nentrypoints = []\n"
    )
    return prefix


def test_a_uv_tool_installed_from_a_pinned_git_ref_cannot_be_moved_by_uv_tool_upgrade(tmp_path):
    prefix = write_receipt(
        tmp_path,
        '{ name = "esbi-cli", git = "https://github.com/RubenAmaury/esbi-cli", rev = "v0.1.0" }',
    )

    pin = pinned_source(prefix)
    text = manual_message("uv-tool", "0.2.0", pin)

    assert pin == ("git", "https://github.com/RubenAmaury/esbi-cli")
    assert "cannot" in text
    assert "uv tool install --force git+https://github.com/RubenAmaury/esbi-cli@v0.2.0" in text


def test_a_uv_tool_installed_from_a_wheel_says_to_download_the_new_one(tmp_path):
    prefix = write_receipt(
        tmp_path, '{ name = "esbi-cli", url = "https://x.test/esbi_cli-0.1.0-py3-none-any.whl" }'
    )

    pin = pinned_source(prefix)
    text = manual_message("uv-tool", "0.2.0", pin)

    assert pin is not None and pin[0] == "wheel"
    assert "releases/tag/v0.2.0" in text and "uv tool install --force" in text


@pytest.mark.parametrize(
    "requirement",
    [
        '{ name = "esbi-cli", git = "https://github.com/RubenAmaury/esbi-cli" }',  # follows main
        '{ name = "esbi-cli", git = "https://github.com/RubenAmaury/esbi-cli", branch = "main" }',
        '{ name = "esbi-cli" }',
    ],
)
def test_a_uv_tool_that_follows_a_branch_or_an_index_is_upgradable(tmp_path, requirement):
    assert pinned_source(write_receipt(tmp_path, requirement)) is None


def test_a_missing_or_broken_receipt_is_not_a_pin(tmp_path):
    assert pinned_source(tmp_path) is None
    (tmp_path / "uv-receipt.toml").write_text("not [ toml")
    assert pinned_source(tmp_path) is None


def test_a_git_url_in_a_receipt_is_quoted_so_it_cannot_become_a_second_command(tmp_path):
    prefix = write_receipt(
        tmp_path, '{ name = "esbi-cli", git = "https://x.test/a; rm -rf ~", rev = "v0.1.0" }'
    )

    text = manual_message("uv-tool", "0.2.0", pinned_source(prefix))

    assert "'git+https://x.test/a; rm -rf ~@v0.2.0'" in text


def test_editable_and_unknown_installs_get_a_human_message():
    assert "git pull" in manual_message("editable", "0.2.0") and "uv sync" in manual_message(
        "editable", "0.2.0"
    )
    unknown = manual_message("unknown", "0.2.0")
    for command in ("brew upgrade", "uv tool upgrade", "pipx upgrade"):
        assert command in unknown
