"""The release flow: what each job may do, what stays off until the maintainer turns it on, and the
formula the tap receives."""

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
RELEASE = yaml.safe_load(
    (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
)
JOBS = RELEASE["jobs"]


def test_only_the_release_job_can_write_to_the_repository_and_only_publishing_gets_an_identity():
    assert RELEASE["permissions"] == {"contents": "read"}
    writers = [n for n, j in JOBS.items() if j.get("permissions", {}).get("contents") == "write"]
    assert writers == ["release"]
    assert [n for n, j in JOBS.items() if "id-token" in j.get("permissions", {})] == [
        "publish-pypi"
    ]


def test_the_build_runs_before_anything_is_published_and_the_artifacts_are_shared_not_rebuilt():
    assert JOBS["build"]["needs"] == "test"
    for name in ("release", "publish-pypi"):
        assert JOBS[name]["needs"] == "build"
        steps = " ".join(s.get("uses", "") for s in JOBS[name]["steps"])
        assert "download-artifact" in steps and "uv build" not in str(JOBS[name]["steps"])


def test_publishing_to_pypi_stays_off_until_the_maintainer_switches_it_on():
    job = JOBS["publish-pypi"]
    assert job["if"] == "vars.PYPI_PUBLISH == 'true'"
    assert job["environment"] == "pypi"


def test_the_tap_update_stays_off_until_enabled_and_is_the_only_job_that_sees_a_secret():
    assert JOBS["update-tap"]["if"] == "vars.TAP_UPDATE == 'true'"
    assert JOBS["update-tap"]["needs"] == "release"
    for name, job in JOBS.items():
        mentions_secret = "secrets.HOMEBREW_TAP_TOKEN" in str(job)
        assert mentions_secret == (name == "update-tap"), name


def test_the_formula_for_the_tap_carries_the_tag_and_the_commit_and_nothing_else_changes():
    revision = "a" * 40
    done = subprocess.run(
        ["bash", str(ROOT / "scripts" / "render-formula.sh"), "v9.8.7", revision],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert done.returncode == 0, done.stderr
    template = (ROOT / "packaging" / "homebrew" / "esbi-cli.rb").read_text(encoding="utf-8")
    assert 'tag:      "v9.8.7"' in done.stdout and f'revision: "{revision}"' in done.stdout
    assert "REPLACE_WITH_THE_COMMIT_OF_THE_TAG" not in done.stdout
    kept = [
        line for line in template.splitlines() if "tag:" not in line and "revision:" not in line
    ]
    assert all(line in done.stdout.splitlines() for line in kept)


def test_the_formula_script_refuses_a_malformed_tag_or_revision():
    for args in (["9.8.7", "a" * 40], ["v9.8.7", "not-a-sha"], ["v9.8.7"]):
        done = subprocess.run(
            ["bash", str(ROOT / "scripts" / "render-formula.sh"), *args],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        assert done.returncode != 0, args
