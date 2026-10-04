#!/usr/bin/env bash
# Install a built wheel in a clean environment and run what a new user runs first. Fails on any
# traceback, which unit tests (that fake the network and the install) cannot see.
# Usage: scripts/smoke.sh dist/esbi_cli-X.Y.Z-py3-none-any.whl
set -euo pipefail
wheel="${1:?usage: smoke.sh path/to/esbi_cli-*.whl}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

uv venv -q "$work/venv"
uv pip install -q --python "$work/venv/bin/python" "$wheel"
sb="$work/venv/bin/sb"
export XDG_CACHE_HOME="$work/cache"
unset ESBI_NO_UPDATE_CHECK ESBI_CONFIG

failures=0
run() {  # run a command (output captured, exit status ignored: a missing model is not a crash)
  local out
  out="$("$@" 2>&1)" || true
  if grep -q "Traceback" <<<"$out"; then
    echo "$out" | head -30
    echo "FAIL: a traceback from: ${*#"$work"/}"
    failures=$((failures + 1))
  else
    echo "ok:   ${*#"$work"/}"
  fi
}

run "$sb" version
run "$sb" version --check
run "$sb" update --dry-run
run "$sb" init --vault "$work/vault" --config-file "$work/config.toml" --model local --no-obsidian
run "$sb" doctor --config "$work/config.toml"
run "$sb" status --config "$work/config.toml"
# a command in a real terminal, with an empty cache: this is where the update notice runs
run python3 -c 'import pty, sys; sys.exit(pty.spawn(sys.argv[1:]))' "$sb" status --config "$work/config.toml"

[ "$failures" -eq 0 ] || { echo "$failures smoke check(s) failed"; exit 1; }
echo "smoke test passed"
