# sourced by the step scripts: installs uv and esbi-cli (PyPI, or the local wheel with WHEEL=1) quietly
curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
export PATH="$HOME/.local/bin:$PATH"
if [ "${WHEEL:-0}" = 1 ]; then uv tool install /dist/esbi_cli-*.whl >/dev/null 2>&1; else uv tool install esbi-cli >/dev/null 2>&1; fi
export NO_COLOR=1
run() { echo; echo "\$ $*"; "$@" 2>&1 | head -${LINES_MAX:-60}; echo "[exit=${PIPESTATUS[0]}]"; }
sh_() { echo; echo "\$ $1"; bash -c "$1" 2>&1 | head -${LINES_MAX:-60}; echo "[exit=${PIPESTATUS[0]}]"; }
sb version
