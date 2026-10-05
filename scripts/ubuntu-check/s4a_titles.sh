#!/bin/bash
# Step 4a: filesystem behaviour on a case-sensitive ext4/overlayfs: case collisions, unicode, long titles,
# paths with spaces, CRLF clips and config. Fake Ollama echoes the clip title back as the page title.
. /h/pre.sh
PY=$(uv python find)
nohup $PY /h/fake_ollama.py >/tmp/fake_ollama.out 2>&1 &
sleep 1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
V="$HOME/My Vault/with space"
sh_ "sb init --vault '$V' --config-file '$HOME/My Config/config.toml' --model local --language en --no-obsidian --nightly none --no-ocr"
export ESBI_CONFIG="$HOME/My Config/config.toml"
BODY='A harness is the code layer that manages context, memory and the verification of results for an AI agent. The harness runs the tools and checks every step before the agent goes on. This clipping is long enough to be read in one go by the model.'
mkdir -p ~/clips
mk() { printf -- "---\ntitle: '%s'\nsource: \"https://example.org/%s\"\n---\n%s Unique id %s.\n" "$2" "$1" "$BODY" "$1" > ~/clips/$1.md; }
mk case1 "Foo"
mk case2 "foo"
mk case3 "FOO"
mk accents "Café résumé ñandú"
mk nfd "$(printf 'Cafe\xcc\x81 re\xcc\x81sume\xcc\x81 n\xcc\x83and\xcc\x81u\xcc\x81')"
mk emoji "Rocket 🚀 launch 日本語のタイトル"
mk windows 'What is AI? A "quick" <guide>: part|1 *really*'
mk long "$($PY -c 'print("L"*300)')"
mk emoji100 "$($PY -c 'print("🚀"*100)')"
mk cjk90 "$($PY -c 'print("日本語"*30)')"
mk reserved "CON"
mk dotted "Trailing dots..."
mk crlf "CRLF clip"
printf -- '---\r\ntitle: "CRLF clip two"\r\nsource: "https://example.org/crlf2"\r\n---\r\n%s two.\r\n' "$BODY" > ~/clips/crlf2.md
sh_ 'sb add ~/clips/*.md'
sh_ 'sb run 2>&1 | grep -v "^    \.\.\."'
sh_ 'cd "$HOME/My Vault/with space" && ls -la wiki/sources | cut -c1-170; ls raw | cut -c1-120; git log --oneline | head -3'
sh_ 'sb lint'
sh_ 'sb status --json | head -c 1500'
# the same vault listed with byte lengths
sh_ 'cd "$HOME/My Vault/with space/wiki/sources" && for f in *; do printf "%s bytes: %s\n" "$(printf %s "$f" | wc -c)" "${f:0:60}"; done'
# CRLF config.toml
sh_ 'sed "s/$/\r/" "$HOME/My Config/config.toml" > ~/crlf.toml; file ~/crlf.toml; sb status --config ~/crlf.toml; sb doctor --config ~/crlf.toml | head -8'
