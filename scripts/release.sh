#!/usr/bin/env bash
# Prepare a release: checks everything is in order, tags it locally, and tells you what to push.
# Usage: scripts/release.sh 0.1.0
# It never pushes: pushing the tag is what publishes, and that is yours to do.
set -euo pipefail
cd "$(dirname "$0")/.."

version="${1:?usage: scripts/release.sh X.Y.Z}"
declared=$(python3 - <<'PY'
import re, pathlib
print(re.search(r'^version = "(.*)"', pathlib.Path("pyproject.toml").read_text(), re.M).group(1))
PY
)
[[ "$declared" == "$version" ]] || { echo "pyproject.toml says $declared, not $version: change it first"; exit 1; }
[[ "$(git branch --show-current)" == "main" ]] || { echo "release from main"; exit 1; }
[[ -z "$(git status --porcelain)" ]] || { echo "commit or stash your changes first"; exit 1; }
git fetch -q origin
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || { echo "main differs from origin/main"; exit 1; }

uv run ruff check .
uv run pytest -q

git tag -a "v$version" -m "esbi-cli $version"
revision=$(git rev-parse "v$version^{commit}")
cat <<MSG

Tagged v$version locally. To publish:
  git push origin v$version          # builds the GitHub release (wheel + sdist)

Then in the Homebrew tap (RubenAmaury/homebrew-esbi-cli, Formula/esbi-cli.rb) change:
  tag:      "v$version",
  revision: "$revision"
and copy packaging/homebrew/esbi-cli.rb over it if the formula itself changed.
MSG
