#!/bin/bash
# Usage: [APT="git pipx"] [EXTRA="--network foo"] ub.sh <ubuntu-tag> <script-in-this-dir> [script args]
# Fresh container, 1 GB limit, fresh non-root user "tester" with an empty HOME, no repo checkout.
# /h = this harness dir (read-only: scripts, pdfs); /dist = locally built wheels (read-only).
set -u
TAG=$1; SCRIPT=$2; shift 2
H="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC2086
docker run --rm --memory 1g --memory-swap 1g ${EXTRA:-} \
  -v "$H":/h:ro -v /tmp/dist-linux:/dist:ro \
  -e SCRIPT="$SCRIPT" -e APT="${APT:-}" -e ROOT="${ROOT:-}" ubuntu:"$TAG" bash -c '
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null && apt-get install -y -qq curl ca-certificates $APT >/dev/null 2>&1 || { echo "APT FAILED"; exit 90; }
useradd -m -s /bin/bash tester
. /etc/os-release; echo "== $PRETTY_NAME, $(uname -m) =="
[ -n "$ROOT" ] && exec bash /h/$SCRIPT "$@"
exec su tester -c "cd ~ && bash /h/$SCRIPT $*"
' -- "$@"
