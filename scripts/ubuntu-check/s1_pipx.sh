#!/bin/bash
# Step 1b: pipx from apt.
python3 --version; pipx --version
echo '$ pipx ensurepath'; pipx ensurepath 2>&1 | tail -3
export PATH="$HOME/.local/bin:$PATH"
echo '$ pipx install esbi-cli'; pipx install esbi-cli 2>&1 | tail -8
which sb
for c in "sb version" "sb update --dry-run" "sb version --check"; do
  echo; echo "\$ $c"; $c 2>&1 | head -40; done
echo '$ sb update (answer n)'; echo n | sb update 2>&1 | head
