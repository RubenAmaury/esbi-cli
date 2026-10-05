# Contributing

Thanks for looking. Bug reports, ideas and pull requests are welcome. By taking part you agree to the [Code of Conduct](.github/CODE_OF_CONDUCT.md). Security problems go through [private reporting](.github/SECURITY.md), not public issues.

## Set up

```bash
git clone https://github.com/RubenAmaury/esbi-cli && cd esbi-cli
uv sync                      # Python 3.12+ and the dependencies
uv run pytest                # 380+ tests; none touch the network, the Keychain or launchd
uv run ruff check .
uv run sb --help
```

If the folder lives in an iCloud-synced location (`~/Documents`), keep the environment outside it, because iCloud flags files inside `.venv` as hidden and Python then ignores them: `export UV_PROJECT_ENVIRONMENT="$HOME/.local/share/venvs/esbi-cli"`.

To work in containers instead (no Python or `uv` on your machine; the venv lives in a Docker volume, never in the folder): `scripts/dev test` builds the hermetic test image (`ruff` and `pytest` run during the build, with no network) and runs it again offline; `scripts/dev lint`, `scripts/dev shell` (the source is bind-mounted, `uv sync` runs first) and `scripts/dev smoke` (installs only the built wheel in a clean image) are the other commands. `PYTHON_VERSION=3.12 scripts/dev test` uses the other supported Python. A container on a Mac has no GPU, so real local models stay on the host: from a shell, a scratch config can reach Ollama at `host.docker.internal:11434`. `.devcontainer/` opens the same `dev` service in VS Code.

To try the app on your own notes without touching a real vault, point `sb init --vault` at a scratch folder and use its config with `--config`.

## Making a change

1. Open an issue first for anything big, so we agree on the direction.
2. Branch from an up-to-date `main`, one change per branch and per pull request: `milestone/<n>-<slug>`, `feature/<slug>` or `fix/<slug>`. `testing` is a trial branch: merge your branch into it to try it out together with other work. Pull requests never come from `testing`, and it is reset to `main` when it drifts.
3. **Test first.** New behaviour starts with a test that fails for the right reason. Tests sit at a few seams (the queue, capture, `run_queue`, the ingest pipeline, the CLI) and use fakes for everything outside the process: `FakeLLM`, a fake IMAP client, a fake Keychain, a fake `launchctl`. A test must never use the network, the real Keychain, launchd, or a real vault.
4. While iterating, run `uv run ruff check .` without `--fix` (it removes imports that the next step is about to use); run `uv run ruff format` before committing.
5. Add a line under *Unreleased* in [CHANGELOG.md](CHANGELOG.md), and say in the pull request description which command, setting or file changed. The documentation is written and built on the maintainer's machine and only the built site is published (https://rubenamaury.github.io/esbi-cli/docs/), so the maintainer updates the pages; a wrong or missing page is welcome as an issue.
6. Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`. A `feat` is a minor version, a `fix` a patch.
7. Open the pull request against `main` and fill in the template.

### What a pull request needs to merge

`main` is protected: it only changes through a pull request, and these checks must pass first. The maintainer merges after reviewing (GitHub does not let an author approve their own pull request, so on this solo project the maintainer's explicit yes is the human gate).

| Check | What it runs |
|---|---|
| `test` | `ruff` and the whole test suite |
| `analyze (python)`, `analyze (actions)` | CodeQL static analysis of the code and of the workflows |
| `dependency-review` | Fails a pull request that adds a dependency with a known high-severity vulnerability |

Dependabot keeps the Python and GitHub Actions dependencies current; every action is pinned to a commit SHA.

## Design rules that keep it working

- **The model never touches files and never needs tool calling.** It returns JSON that matches a schema (`src/esbi_cli/llm/schemas.py`); the program validates it and writes. It must keep working with small local models.
- **Check what the model claims against the source** before writing it (quotes, terms, entities, links). A new field that makes a claim about the source gets a check in `apply_plan`.
- **LLM access only through `esbi_cli.llm.adapter`.** A new provider implements `complete_json` and `tokens_used`.
- **`raw/` is never modified**, risky changes go to `wiki/review/`, secrets live in the Keychain, and email never reaches a model that sends text away.
- Small and boring beats clever. Every setting needs a reason to exist.

How the pieces fit, and how to add a source type, a provider or a note section: [Internals](https://rubenamaury.github.io/esbi-cli/docs/explanation/internals/) and the [Architecture](https://rubenamaury.github.io/esbi-cli/docs/explanation/architecture/) (ports and adapters, and the gotchas worth knowing before you change anything). Known limits: [Known limits](https://rubenamaury.github.io/esbi-cli/docs/explanation/internals/#known-limits). Open work: the issue tracker.

## Releases (maintainer)

Versions follow [Semantic Versioning](https://semver.org/) and every release is a tag. `scripts/release.sh X.Y.Z` checks that `main` is clean and current, runs the tests, and tags locally; pushing the tag publishes (GitHub release, then the Homebrew formula's tag and revision). The changelog section for the version must exist first.

### What pushing a tag does

`git push origin vX.Y.Z` starts the release workflow: the tests run, the wheel and sdist are built once, and then, independently of each other:

| Job | What it does | Switched on by |
|---|---|---|
| `release` | Creates the GitHub release with the wheel, the sdist and the changelog section as notes | always |
| `publish-pypi` | Publishes the package to PyPI through trusted publishing (no stored token) | repository variable `PYPI_PUBLISH = true` |
| `update-tap` | Writes the new tag and commit into the Homebrew formula of the tap, so `brew upgrade` sees the version | repository variable `TAP_UPDATE = true` |

The last two stay off until their one-time setup is done, so a release never fails because a channel is not ready.

**One-time setup, PyPI.** Create an account on pypi.org with two-factor authentication. Under *Your projects > Publishing*, add a pending publisher: project `esbi-cli`, owner `RubenAmaury`, repository `esbi-cli`, workflow `release.yml`, environment `pypi`. In the GitHub repository, *Settings > Environments*, create an environment named `pypi`; then *Settings > Secrets and variables > Actions > Variables*, add `PYPI_PUBLISH` with the value `true`. The next tag creates the project on PyPI.

**One-time setup, Homebrew tap (done).** The `update-tap` job pushes with an SSH deploy key that can write to the tap repository only: its public half is a deploy key on `RubenAmaury/homebrew-esbi-cli`, its private half is the repository secret `HOMEBREW_TAP_DEPLOY_KEY`, and only that job reads it. To switch the job on, add the repository variable `TAP_UPDATE` with the value `true`. To rotate the key, generate a new pair with `ssh-keygen -t ed25519`, replace the deploy key on the tap repository and update the secret.

### Which version number

- Every merge to `main` is a release. A fix or a documentation change is a patch (`0.1.1`); a new feature is a minor (`0.2.0`) while the major version is 0, and anything that breaks a command or the config format says so in the changelog. Tag it, move *Unreleased* under the new version, and let the release workflow build it.
- A published version is never re-tagged or edited: a mistake is fixed by the next patch.
