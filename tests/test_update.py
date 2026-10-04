import httpx
import pytest

from esbi_cli.update import RELEASES_API, is_newer, latest_release, parse_version


@pytest.mark.parametrize(
    ("older", "newer"),
    [
        ("0.1.0", "0.2.0"),
        ("0.9.0", "0.10.0"),  # numbers, not text
        ("v0.1.0", "0.1.1"),
        ("0.2.0.dev0", "0.2.0"),
        ("0.2.0a1", "0.2.0b1"),
        ("0.2.0b2", "0.2.0rc1"),
        ("0.2.0rc1", "0.2.0"),
        ("0.2.0.dev3", "0.2.0a1"),
        ("0.1.9", "0.2.0.dev0"),
    ],
)
def test_versions_compare_as_numbers_and_a_prerelease_is_older_than_its_release(older, newer):
    assert is_newer(newer, older) and not is_newer(older, newer)


def test_the_same_version_is_not_newer_and_a_leading_v_is_ignored():
    assert not is_newer("v0.1.0", "0.1.0")


@pytest.mark.parametrize("text", ["", "0+unknown", "1.2", "1.2.3.4", "latest", "1.2.3-beta", "v"])
def test_text_that_is_not_a_version_does_not_parse_and_is_never_newer(text):
    assert parse_version(text) is None
    assert not is_newer(text, "0.1.0") and not is_newer("9.9.9", text)


def fake_get(body, status=200):
    """A stand-in for netguard.safe_get that records how it was called."""

    def get(url, **kwargs):
        get.calls.append((url, kwargs))
        if isinstance(body, Exception):
            raise body
        return httpx.Response(
            status,
            content=body if isinstance(body, bytes) else None,
            json=None if isinstance(body, bytes) else body,
            request=httpx.Request("GET", url),
        )

    get.calls = []
    return get


GOOD = {
    "tag_name": "v0.2.0",
    "html_url": "https://github.com/RubenAmaury/esbi-cli/releases/tag/v0.2.0",
    "body": "ignored",
}


def test_the_latest_release_is_read_from_the_github_api_with_an_honest_short_request():
    get = fake_get(GOOD)

    release = latest_release(fetch=get)

    assert release.version == "0.2.0" and release.url == GOOD["html_url"]
    ((url, kwargs),) = get.calls
    assert url == RELEASES_API
    assert RELEASES_API == "https://api.github.com/repos/RubenAmaury/esbi-cli/releases/latest"
    assert kwargs["timeout"] == 5
    assert kwargs["headers"]["Accept"] == "application/vnd.github+json"
    assert "esbi-cli" in kwargs["headers"]["User-Agent"]


@pytest.mark.parametrize(
    "get",
    [
        fake_get(httpx.ConnectError("offline")),
        fake_get(httpx.ReadTimeout("slow")),
        fake_get({"message": "rate limit"}, status=403),
        fake_get(b"<html>not json</html>"),
        fake_get([1, 2]),  # JSON, but not an object
        fake_get({}),
    ],
)
def test_any_failure_to_ask_gives_none_and_never_an_error(get):
    assert latest_release(fetch=get) is None


def test_a_refused_address_is_a_failed_check_too():
    from esbi_cli.netguard import UnsafeURL

    assert latest_release(fetch=fake_get(UnsafeURL("private address"))) is None


@pytest.mark.parametrize(
    "tag",
    [
        "v0.2.0-rc1",
        "latest",
        "v0.2.0; rm -rf ~",
        "v٠.١.٢",  # Unicode digits
        "v0.2.0" + "0" * 500,
        "\x1b[31mv0.2.0",
        None,
        7,
    ],
)
def test_a_tag_that_is_not_plain_x_y_z_is_refused(tag):
    assert latest_release(fetch=fake_get({**GOOD, "tag_name": tag})) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/RubenAmaury/esbi-cli/releases",
        "http://github.com/RubenAmaury/esbi-cli/releases",
        "https://github.com/RubenAmaury/esbi-cli-evil/releases",
        "https://github.com.evil.example/RubenAmaury/esbi-cli/x",
        "javascript:alert(1)",
        None,
        "",
    ],
)
def test_a_url_outside_the_project_is_replaced_by_the_project_releases_page(url):
    release = latest_release(fetch=fake_get({**GOOD, "html_url": url}))

    assert release.version == "0.2.0"
    assert release.url == "https://github.com/RubenAmaury/esbi-cli/releases"


def test_control_characters_in_the_url_never_reach_the_terminal():
    url = GOOD["html_url"] + "\x1b]0;pwned\x07"

    release = latest_release(fetch=fake_get({**GOOD, "html_url": url}))

    assert "\x1b" not in release.url and "\x07" not in release.url
