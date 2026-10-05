#!/bin/bash
# Step 5: sb update for real, from 0.2.1 to the latest, with uv and with pipx (needs APT="pipx"; Ubuntu 24.04 only for pipx).
curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
export PATH="$HOME/.local/bin:$PATH" NO_COLOR=1
echo "##### uv tool: install 0.2.1, then sb update"
uv tool install esbi-cli==0.2.1 2>&1 | tail -2
sb version
echo "(banner on a normal command: the automatic update notice)"; sb status 2>&1 | head -3
sb update --yes 2>&1 | tail -12
sb version
echo "##### pipx: install 0.2.1, then sb update"
uv tool uninstall esbi-cli >/dev/null 2>&1
pipx install esbi-cli==0.2.1 2>&1 | tail -2
hash -r; sb version
sb update --yes 2>&1 | tail -12
sb version
