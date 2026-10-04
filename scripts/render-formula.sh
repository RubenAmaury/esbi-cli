#!/usr/bin/env bash
# Print the Homebrew formula for a release: the template in packaging/homebrew with this release's
# tag and commit. Usage: scripts/render-formula.sh v0.2.0 <40-hex commit>
set -euo pipefail
cd "$(dirname "$0")/.."

tag="${1:-}"
revision="${2:-}"
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "usage: render-formula.sh vX.Y.Z <commit sha>" >&2; exit 1; }
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo "the revision must be a full 40-character commit sha" >&2; exit 1; }

sed -E \
  -e "s/^(      tag:      )\"v[0-9.]+\",$/\1\"$tag\",/" \
  -e "s/^(      revision: )\"[^\"]*\"$/\1\"$revision\"/" \
  packaging/homebrew/esbi-cli.rb
