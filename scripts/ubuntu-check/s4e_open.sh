#!/bin/bash
# Step 4e: how the vault is opened when obsidian is absent: `open` may be openvt (kbd), xdg-open or nothing (WSL).
. /h/pre.sh
echo "open: $(command -v open || echo none) -> $(readlink -f $(command -v open) 2>/dev/null)"
sb init --vault ~/v --model local --language en --obsidian --nightly none --no-ocr >/dev/null
grep -n "viewer" ~/.config/esbi-cli/config.toml
sh_ 'sb today'
sh_ 'strace -V >/dev/null 2>&1; open --help 2>&1 | head -3'
sh_ 'sb setup clipper </dev/null 2>&1 | head -30'
