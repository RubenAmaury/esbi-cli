"""The container tooling's own rules: pinned images, a hermetic test stage, a clean smoke stage."""

import json
import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
FROM = re.compile(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", re.M | re.I)


def _stage(name):
    """The lines of one Dockerfile stage."""
    parts = re.split(r"^(?=FROM )", DOCKERFILE, flags=re.M)
    return next(p for p in parts if re.match(rf"FROM \S+ AS {re.escape(name)}\s", p))


def _supported_pythons():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return {
        c.rsplit(" ", 1)[1]
        for c in meta["classifiers"]
        if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)
    }


def test_every_image_the_dockerfile_pulls_is_pinned_by_digest():
    stages = {name for _, name in FROM.findall(DOCKERFILE) if name}
    pulled = [img for img, _ in FROM.findall(DOCKERFILE) if img not in stages and "${" not in img]
    assert pulled, "the Dockerfile pulls no image?"
    for image in pulled:
        assert re.search(r"@sha256:[0-9a-f]{64}$", image), f"{image} is not pinned by digest"


def test_a_python_base_stage_exists_for_every_supported_version():
    """requires-python is a floor, so the matrix is the versions the package says it supports."""
    stages = {name for _, name in FROM.findall(DOCKERFILE) if name}
    assert {s.removeprefix("python-") for s in stages if s.startswith("python-")} == (
        _supported_pythons()
    )


def test_the_test_stage_runs_ruff_and_pytest_with_no_network():
    assert re.search(r"^RUN --network=none .*ruff check .*pytest", _stage("test"), re.M)


def test_the_smoke_stage_holds_the_wheel_only_and_runs_as_a_non_root_user():
    smoke = _stage("smoke")
    copies = re.findall(r"^COPY (?:--from=\S+ )?(\S+)", smoke, re.M)
    assert sorted(copies) == ["/dist/*.whl", "scripts/smoke.sh"]  # no source tree
    assert re.search(r"^USER smoke$", smoke, re.M)
    assert "useradd" in smoke and "--no-create-home" in smoke  # an empty HOME, not /etc/skel


def test_the_dev_stage_runs_as_a_non_root_user_with_the_venv_outside_the_source():
    dev = _stage("dev")
    assert re.search(r"^USER dev$", dev, re.M) and "UV_PROJECT_ENVIRONMENT=/opt/venv" in dev
    assert "ARG UID" in dev


def test_compose_has_the_three_services_and_the_offline_ones_have_no_network():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert set(services) == {"dev", "test", "smoke"}
    assert all(s.get("mem_limit") for s in services.values())  # a shared 8 GB machine
    assert services["test"]["network_mode"] == services["smoke"]["network_mode"] == "none"
    assert {s["build"]["target"] for s in services.values()} == {"dev", "test", "smoke"}
    assert (ROOT / "scripts" / "dev").stat().st_mode & 0o111


def test_the_build_context_leaves_out_secrets_history_and_local_state():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for name in (".git", ".venv", "config.toml", ".env"):
        assert name in ignored


def test_the_devcontainer_uses_the_dev_service():
    config = json.loads((ROOT / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8"))
    assert config["service"] == "dev" and config["dockerComposeFile"] == ["../compose.yaml"]
    assert config["remoteUser"] == "dev"


def test_the_docker_workflow_covers_every_supported_python_with_least_privilege():
    path = ROOT / ".github" / "workflows" / "docker.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    job = workflow["jobs"]["docker"]
    assert set(job["strategy"]["matrix"]["python"]) == _supported_pythons()
    assert workflow["permissions"] == {"contents": "read"}
    checkout = next(s for s in job["steps"] if "actions/checkout" in s.get("uses", ""))
    assert checkout["with"]["persist-credentials"] is False
    text = path.read_text(encoding="utf-8")
    assert "secrets." not in text and "push: true" not in text
    steps = [s for s in job["steps"] if "build-push-action" in s.get("uses", "")]
    assert [s["with"]["target"] for s in steps] == ["test", "smoke"]
