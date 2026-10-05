#!/bin/bash
# Step 2: init, doctor, schedule, email. Empty HOME, no git (APT unset), no ollama, no obsidian.
. /h/pre.sh
echo "git: $(command -v git || echo none)  open: $(command -v open || echo none)  xdg-open: $(command -v xdg-open || echo none)  caffeinate: $(command -v caffeinate || echo none)"
sh_ 'sb init --vault ~/vault --model local --language en --no-obsidian --nightly none --no-ocr'
sh_ 'ls -la ~/vault ~/.config/esbi-cli; cat ~/.config/esbi-cli/config.toml | head -50'
run sb doctor
run sb doctor --json
run sb info
run sb status --json
run sb schedule status
run sb schedule install
run sb schedule uninstall
run sb email set-password
sh_ 'echo "hunter2" | sb email set-password'
run sb email fetch
run sb email configure --help
run sb setup email
run sb today
# interactive init with piped answers, fresh vault + config
sh_ 'printf "~/vault2\n\nn\n\n\n\n\n\n\n\n\n\n" | sb init --config-file ~/c2.toml'
sh_ 'ls ~/vault2; head -30 ~/c2.toml'
sh_ 'sb init --vault ~/vault --nightly 03:00 --model local --language en --no-obsidian --config-file ~/c3.toml'
sh_ 'sb init --vault ~/vault4 --nightly 03:00 --model local --language en --no-obsidian --config-file ~/c4.toml'
