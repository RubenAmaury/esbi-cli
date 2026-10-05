# syntax=docker/dockerfile:1
# Development and hermetic build-and-test images for esbi-cli. Dev tooling only: nothing here is
# shipped, and the app behaves the same with or without it. Usage: `scripts/dev` (see compose.yaml).
#
#   dev    a shell with the source bind-mounted and the venv in a named volume
#   test   copies the source, installs the locked dependencies, runs ruff and pytest with no network
#   wheel  builds the wheel and the sdist
#   smoke  installs ONLY the wheel (no source tree) as a non-root user with an empty HOME
#
# PYTHON_VERSION picks 3.12 or 3.13 (requires-python is >=3.12): --build-arg PYTHON_VERSION=3.12

ARG PYTHON_VERSION=3.13

# One pinned digest per supported version (Dependabot keeps both current).
FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3 AS python-3.12
FROM python:3.13-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed AS python-3.13
FROM ghcr.io/astral-sh/uv:0.12.21@sha256:a7aed3216253ee804de3e2d8afa5073baa1a177335345d43845cd4165e43b711 AS uv

FROM python-${PYTHON_VERSION} AS base
COPY --from=uv /uv /usr/local/bin/uv
# The image's own Python is the one to use: .python-version says 3.13, which a 3.12 image lacks.
ENV UV_PYTHON=/usr/local/bin/python \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=0 \
    UV_NO_PROGRESS=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Tools that need git (the vault is a git repo) get it; the smoke image deliberately has none.
FROM base AS base-git
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# ---- dev: the project is installed (editable) at run time from the bind mount, see scripts/dev ----
FROM base-git AS dev
ARG UID=1000
RUN useradd --create-home --uid "$UID" dev \
    && mkdir /opt/venv /workspace \
    && chown dev /opt/venv /workspace
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    ESBI_NO_UPDATE_CHECK=1
USER dev
WORKDIR /workspace
CMD ["bash"]

# ---- test: hermetic. The network is only used while installing; ruff and pytest run without it ----
FROM base-git AS test
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    ESBI_NO_UPDATE_CHECK=1
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-install-project
COPY . .
RUN uv sync --locked
# A git identity for tests that commit; set here because the build has no host ~/.gitconfig.
RUN git config --global user.name test && git config --global user.email test@example.com
RUN --network=none ruff check . && pytest -q

# ---- wheel ----
FROM base AS wheel
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv build --out-dir /dist

# ---- smoke: a clean user machine. Only the wheel and the smoke script, no source tree ----
FROM base AS smoke
ENV UV_CACHE_DIR=/opt/uv-cache \
    SMOKE_NO_KEYCHAIN=1
RUN useradd --no-create-home --home-dir /home/smoke --uid 1000 smoke \
    && mkdir /home/smoke "$UV_CACHE_DIR" \
    && chown smoke /home/smoke "$UV_CACHE_DIR"
COPY --from=wheel /dist/*.whl /wheel/
COPY scripts/smoke.sh /smoke/smoke.sh
USER smoke
WORKDIR /home/smoke
# Install and check once with the network (this fills the uv cache), then the container's own
# command repeats it offline: what a first-time user does, on a machine with no model and no mail.
RUN bash /smoke/smoke.sh /wheel/*.whl
ENV UV_OFFLINE=1
CMD ["bash", "-c", "bash /smoke/smoke.sh /wheel/*.whl && test -z \"$(ls -A /home/smoke)\""]
