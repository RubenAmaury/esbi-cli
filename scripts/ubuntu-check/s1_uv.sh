#!/bin/bash
# Step 1a: install like a user with uv from PyPI.
echo '$ curl -LsSf https://astral.sh/uv/install.sh | sh'
curl -LsSf https://astral.sh/uv/install.sh | sh 2>&1 | tail -5
export PATH="$HOME/.local/bin:$PATH"
echo '$ uv tool install esbi-cli'; uv tool install esbi-cli 2>&1 | tail -8; echo "exit=$?"
which sb
for c in "sb version" "sb --help" "sb update --dry-run" "sb version --check"; do
  echo; echo "\$ $c"; $c 2>&1 | head -40; echo "exit=${PIPESTATUS[0]}"
done
