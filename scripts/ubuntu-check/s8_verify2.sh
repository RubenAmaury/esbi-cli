#!/bin/bash
# Step 8 (ROOT=1, APT="git"): the second round of fixes with the fixed wheel, in a fresh Ubuntu.
useradd -m -s /bin/bash tester2 2>/dev/null
cat > /tmp/inner.sh <<'EOS'
export WHEEL=1
. /h/pre.sh
PY=$(uv python find)
nohup $PY /h/fake_ollama.py >/tmp/fake_ollama.out 2>&1 &
sleep 1
sh_ 'sb init --vault ~/vault --model local --language en --no-obsidian --nightly none --no-ocr | tail -3; cd ~/vault && git status --short; git log --format="%an %s"'
BODY='A harness is the code layer that manages context, memory and the verification of results for an AI agent. The harness runs the tools and checks every step before the agent goes on. This clipping is long enough to be read in one go by the model.'
mkdir -p ~/clips
for n in 1 2 3 4; do printf -- "---\ntitle: 'Clip %s'\n---\n%s Unique %s.\n" $n "$BODY" $n > ~/clips/c$n.md; done
sb add ~/clips/*.md >/dev/null
echo "##### sb run | head -1 (reader leaves)"
DELAY=0 sb run | head -1; echo "pipeline status: ${PIPESTATUS[0]}"
sb status --json | head -c 400; echo
echo "##### schedule status"
sb schedule status; echo "[exit=$?]"
echo "##### read-only vault"
chmod -R a-w ~/vault
sh_ 'sb add ~/clips/c1.md'
sh_ 'sb run'
sh_ 'sb run --json'
sh_ 'sb lint'
sh_ 'sb ask "what is a harness"'
chmod -R u+w ~/vault
echo "##### init into an unwritable HOME-like folder"
mkdir -p ~/ro && chmod 555 ~/ro
sh_ 'sb init --vault ~/ro/v --config-file ~/c.toml'
EOS
su tester2 -c "bash /tmp/inner.sh"
echo "##### uid 4242 with no home"
su tester2 -c 'curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1; export PATH=$HOME/.local/bin:$PATH; WHEEL=1; uv tool install /dist/esbi_cli-*.whl >/dev/null 2>&1'
chmod 755 /home/tester2; chmod -R a+rX /home/tester2/.local
cat > /tmp/nohome.sh <<'EOS'
export PATH=/home/tester2/.local/bin:$PATH ESBI_NO_UPDATE_CHECK=1
id; echo "HOME=[${HOME:-unset}]"
echo '$ sb version'; sb version 2>&1 | tail -2
echo '$ sb status'; sb status 2>&1 | tail -2
echo '$ sb init'; sb init 2>&1 | tail -2
echo '$ sb doctor'; sb doctor 2>&1 | head -3
EOS
setpriv --reuid=4242 --regid=4242 --clear-groups env -u HOME bash /tmp/nohome.sh
