#!/bin/bash
# Step 4b: environment edge cases. No git installed (APT unset). Fake Ollama with a 4 s delay per call for the lock test.
. /h/pre.sh
PY=$(uv python find)
DELAY=4 nohup $PY /h/fake_ollama.py >/tmp/fake_ollama.out 2>&1 &
sleep 1
echo "git: $(command -v git || echo none)  caffeinate: $(command -v caffeinate || echo none)  TZ=${TZ:-unset}  LANG=${LANG:-unset}  LC_ALL=${LC_ALL:-unset}  locale: $(locale 2>&1 | head -1)"
sb init --vault ~/v --model local --language en --no-obsidian --nightly none --no-ocr >/dev/null
export ESBI_CONFIG=~/.config/esbi-cli/config.toml
BODY='A harness is the code layer that manages context, memory and the verification of results for an AI agent. The harness runs the tools and checks every step before the agent goes on. This clipping is long enough to be read in one go by the model.'
mkdir -p ~/clips
for n in a b c; do printf -- "---\ntitle: 'Clip $n café ñ'\nsource: \"https://example.org/$n\"\n---\n%s Unique $n.\n" "$BODY" > ~/clips/$n.md; done
sb add ~/clips/a.md ~/clips/b.md >/dev/null

echo "##### no git: run"
sh_ 'sb run 2>&1 | grep -v "^    \.\.\."'
sh_ 'ls ~/v ~/v/.esbi; ls -la ~/v/.esbi | head'

echo "##### lock: two concurrent runs (DELAY=4)"
sb add ~/clips/c.md >/dev/null
(sb run > /tmp/run1.out 2>&1 &) ; sleep 2
sh_ 'sb run'
sh_ 'sb run --json | head -3'
sh_ 'sb run --if-due'
sleep 12; sh_ 'cat /tmp/run1.out | grep -v "^    \.\.\."'
sh_ 'ls -la ~/v/.esbi/; ls -la ~/v/.esbi/run.lock'

echo "##### permissions / umask"
sh_ 'stat -c "%a %n" ~/v ~/v/.esbi ~/v/.esbi/* ~/.config/esbi-cli ~/.config/esbi-cli/config.toml ~/.cache/esbi-cli/* 2>&1'
sh_ 'umask 077; sb init --vault ~/v77 --config-file ~/c77.toml --model local --language en --no-obsidian --nightly none --no-ocr --base-url http://localhost:11434 >/dev/null; sb add ~/clips/a.md --config ~/c77.toml; stat -c "%a %n" ~/v77 ~/v77/.esbi ~/v77/.esbi/* ~/c77.toml'

echo "##### read-only vault"
sh_ 'chmod -R a-w ~/v; sb add ~/clips/c.md; sb status; sb run 2>&1 | tail -4; sb today 2>&1 | tail -3; sb lint 2>&1 | tail -3; sb ask "what is a harness" 2>&1 | tail -3; chmod -R u+w ~/v'

echo "##### read-only HOME (config via ESBI_CONFIG elsewhere; update check ON)"
sh_ 'mkdir -p /tmp/cfg && cp ~/.config/esbi-cli/config.toml /tmp/cfg/ && chmod 555 ~ && rm -rf ~/.cache; env -u ESBI_NO_UPDATE_CHECK ESBI_CONFIG=/tmp/cfg/config.toml sb status; env ESBI_CONFIG=/tmp/cfg/config.toml sb version --check; env ESBI_CONFIG=/tmp/cfg/config.toml sb doctor | head -5; chmod 755 ~'

echo "##### locale"
sh_ 'LC_ALL=C sb ask "¿qué es un arnés? café ñ" ; echo; LC_ALL=C sb status; locale 2>&1 | head -2'
sh_ 'LC_ALL=C PYTHONUTF8=0 PYTHONCOERCECLOCALE=0 sb ask "¿qué es un arnés? café ñ" 2>&1 | tail -4'
sh_ 'LC_ALL=C PYTHONUTF8=0 PYTHONCOERCECLOCALE=0 sb status 2>&1 | tail -3; LC_ALL=C PYTHONUTF8=0 PYTHONCOERCECLOCALE=0 sb doctor 2>&1 | tail -3'
sh_ 'LC_ALL=C PYTHONUTF8=0 PYTHONCOERCECLOCALE=0 sb lint 2>&1 | tail -3; PYTHONIOENCODING=ascii sb ask "what is a harness" 2>&1 | tail -3'
sh_ 'LC_ALL=C PYTHONUTF8=0 PYTHONCOERCECLOCALE=0 sb --help 2>&1 | head -5'
sh_ 'LC_ALL=C PYTHONUTF8=0 PYTHONCOERCECLOCALE=0 sb run --limit 1 2>&1 | tail -3; ls ~/v/wiki/sources'

echo "##### HOME unset, and a uid without passwd entry"
sh_ 'env -u HOME sb version; env -u HOME sb status 2>&1 | tail -3'
cat > /tmp/nohome.sh <<'EOS'
export PATH=/home/tester/.local/bin:$PATH
id; echo "HOME=[${HOME:-unset}]"
sb version
sb status 2>&1 | tail -3
sb init --vault /tmp/vnh --config-file /tmp/cnh.toml --model local --language en --no-obsidian --nightly none --no-ocr 2>&1 | tail -3
sb status --config /tmp/cnh.toml 2>&1 | tail -3
sb doctor --config /tmp/cnh.toml 2>&1 | head -6
EOS
echo "(uid 4242 test is run by the wrapper below)"
