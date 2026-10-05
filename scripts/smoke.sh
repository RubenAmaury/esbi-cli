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

# a real PDF through the installed wheel: its PDF engine is a compiled library that unit tests
# running from the source tree do not load the way a user's install does
pdf="$(cd "$(dirname "$0")/.." && pwd)/tests/fixtures/pdf/paper.pdf"
if out="$("$work/venv/bin/python" -c '
import sys
from esbi_cli.extract import extract_source
doc = extract_source(sys.argv[1])
assert "## 1 Introduction" in doc.text, "headings were not found"
assert "enables small models" in doc.text, "the text was not read"
assert len(doc.figures) == 1 and doc.figures[0].data[:4] == b"\x89PNG", "the figure was not rendered"
print("read a PDF: %d characters, %d figure" % (len(doc.text), len(doc.figures)))
' "$pdf" 2>&1)"; then
  echo "ok:   read $(basename "$pdf") with the installed wheel ($out)"
else
  echo "$out" | head -30
  echo "FAIL: reading a PDF with the installed wheel"
  failures=$((failures + 1))
fi

expect() {  # expect <text> <command...>: the command's output must contain the text (no traceback either)
  local want="$1" out
  shift
  out="$("$@" 2>&1)" || true
  if grep -q "Traceback" <<<"$out" || ! grep -qF -- "$want" <<<"$out"; then
    echo "$out" | head -30
    echo "FAIL: expected \"$want\" from: ${*#"$work"/}"
    failures=$((failures + 1))
  else
    echo "ok:   ${*#"$work"/} says \"$want\""
  fi
}

# What the docs promise where there is no launchd (Linux), and no Keychain (SMOKE_NO_KEYCHAIN=1,
# set by the container: a CI runner may have a secret service, so it is not assumed there).
if [ "$(uname)" = Linux ]; then
  expect "only macOS has" "$sb" schedule install --config "$work/config.toml"
  expect "sb run --if-due" "$sb" schedule status
  expect "only macOS has" "$sb" schedule uninstall
fi
if [ -n "${SMOKE_NO_KEYCHAIN:-}" ]; then
  sed -i -e 's/^enabled = false/enabled = true/' -e 's/^# user = .*/user = "me@example.test"/' \
    "$work/config.toml"
  expect "There is no keyring on this system" "$sb" email set-password --stdin --config "$work/config.toml" <<<"pw"
  expect "There is no keyring on this system" "$sb" email fetch --config "$work/config.toml"
  expect "There is no keyring on this system" "$sb" doctor --config "$work/config.toml"
fi

[ "$failures" -eq 0 ] || { echo "$failures smoke check(s) failed"; exit 1; }
echo "smoke test passed"
