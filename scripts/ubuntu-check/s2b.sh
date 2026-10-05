#!/bin/bash
# Step 2b: interactive init through a pty, obsidian viewer without obsidian, email on without a secret service, open=openvt.
. /h/pre.sh
echo "which script: $(command -v script)  open: $(command -v open || echo none)"
# answers in order: vault, language(1), obsidian(y), model(1), runtime(1), base url(empty), nightly(y), time, (git absent -> no remote), then maybe integrations
sh_ 'printf "~/v2\n1\ny\n1\n1\n\ny\n04:30\n\n\n\n\n" | script -qec "sb init --config-file ~/c2.toml" /dev/null'
sh_ 'ls ~/v2 | head -3; grep -nE "viewer|nightly_time|vault =" ~/c2.toml'
run sb doctor --config ~/c2.toml
run sb today --config ~/c2.toml
# email enabled, no secret service (keyring has no backend in a container)
run sb email configure --user someone@gmail.com --config ~/c2.toml
sh_ 'echo "abcd efgh ijkl mnop" | sb email set-password --config ~/c2.toml'
sh_ 'printf "abcd efgh ijkl mnop\n" | script -qec "sb email set-password --config ~/c2.toml" /dev/null'
run sb email fetch --config ~/c2.toml
run sb doctor --config ~/c2.toml
run sb doctor --json --config ~/c2.toml
