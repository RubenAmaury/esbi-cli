#!/bin/bash
# Step 7: the fixed wheel (WHEEL=1) in a fresh Ubuntu with git but NO git identity. Re-checks every fix.
export WHEEL=1
. /h/pre.sh
PY=$(uv python find)
nohup $PY /h/fake_ollama.py >/tmp/fake_ollama.out 2>&1 &
sleep 1
sh_ 'sb init --vault ~/vault --model local --language en --no-obsidian --nightly 03:00 --no-ocr | tail -6'
BODY='A harness is the code layer that manages context, memory and the verification of results for an AI agent. The harness runs the tools and checks every step before the agent goes on. This clipping is long enough to be read in one go by the model.'
mkdir -p ~/clips
mk() { printf -- "---\ntitle: '%s'\nsource: \"https://example.org/%s\"\n---\n%s Unique id %s.\n" "$2" "$1" "$BODY" "$1" > ~/clips/$1.md; }
mk c1 "Foo"; mk c2 "foo"; mk c3 "FOO"; mk c4 "Café"; mk c5 "$(printf 'Cafe\xcc\x81')"
mk c6 "$($PY -c 'print("日本語"*30)')"; mk c7 "$($PY -c 'print("🚀"*100)')"
sb add ~/clips/*.md >/dev/null
sh_ 'sb run 2>&1 | grep -v "^    \.\.\." | cut -c1-120'
sh_ 'cd ~/vault && ls wiki/sources | cut -c1-60; git log --format="%an <%ae> %s" | head -3 | cut -c1-100; git status --short | head -3'
sh_ 'sb status'
sh_ 'sb schedule status'
sh_ 'env -i HOME=$HOME PATH=/usr/bin:/bin $(sb schedule status 2>&1 | tail -1 | sed "s/^ *0 \* \* \* \* //")'
sh_ 'sb doctor | grep -A1 -E "model|nightly"'
sh_ 'sb export --help | grep -i default'
sh_ 'sb init --vault ~/v2 --model local --language en --obsidian --nightly none --no-ocr --config-file ~/c2.toml >/dev/null; sb today --config ~/c2.toml'
