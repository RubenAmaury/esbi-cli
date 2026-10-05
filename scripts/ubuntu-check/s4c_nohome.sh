#!/bin/bash
# Step 4c (runs as ROOT, ROOT=1): install esbi-cli for tester, then run it as uid 4242, which has no passwd entry and no HOME.
chmod 755 /home/tester
su tester -c 'curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1; export PATH=$HOME/.local/bin:$PATH; uv tool install esbi-cli >/dev/null 2>&1; sb version'
chmod -R a+rX /home/tester/.local
cat > /tmp/nohome.sh <<'EOS'
export PATH=/home/tester/.local/bin:$PATH
export ESBI_NO_UPDATE_CHECK=1
id; echo "HOME=[${HOME:-unset}]"
echo '$ sb version'; sb version 2>&1 | tail -3
echo '$ sb status'; sb status 2>&1 | tail -4
echo '$ sb init (vault and config given explicitly)'
sb init --vault /tmp/vnh --config-file /tmp/cnh.toml --model local --language en --no-obsidian --nightly none --no-ocr 2>&1 | tail -4
echo '$ sb status --config'; sb status --config /tmp/cnh.toml 2>&1 | tail -4
echo '$ sb doctor'; sb doctor --config /tmp/cnh.toml 2>&1 | head -8
echo '$ sb init with defaults'; sb init 2>&1 | tail -4
echo '$ sb version --check (update cache with no HOME)'; env -u ESBI_NO_UPDATE_CHECK sb version --check 2>&1 | tail -4
EOS
mkdir -p /tmp/vnh; chmod 777 /tmp
echo "=== uid 4242, HOME unset"
setpriv --reuid=4242 --regid=4242 --clear-groups env -u HOME bash /tmp/nohome.sh
echo "=== uid 4242, HOME=/nonexistent"
setpriv --reuid=4242 --regid=4242 --clear-groups env HOME=/nonexistent bash /tmp/nohome.sh
