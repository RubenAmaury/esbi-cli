#!/bin/bash
# Step 6 (ROOT=1, EXTRA=--privileged, APT="dosfstools util-linux git"): a vault on a case-insensitive vfat volume mounted at
# "/mnt/c/Users/Ruben Melo/Documents", the nearest thing to WSL's /mnt/c (NTFS through drvfs) that a container can mount.
set -u
U=$(id -u tester); G=$(id -g tester)
MNT="/mnt/c/Users/Ruben Melo/Documents"
mkdir -p "$MNT"
truncate -s 128M /tmp/c.img && mkfs.vfat -n WINC /tmp/c.img >/dev/null
mount -o loop,uid=$U,gid=$G,fmask=0022,dmask=0022,iocharset=utf8 /tmp/c.img "$MNT" || { echo "MOUNT FAILED"; exit 1; }
echo "mounted: $(findmnt -no FSTYPE,OPTIONS "$MNT" | cut -c1-120)"
touch "$MNT/Foo.md"; touch "$MNT/foo.md" 2>&1; ls "$MNT"; rm -f "$MNT/Foo.md"
chmod 600 "$MNT" 2>&1 | head -1
cat > /tmp/inner.sh <<'EOS'
curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
export PATH="$HOME/.local/bin:$PATH" NO_COLOR=1
uv tool install esbi-cli >/dev/null 2>&1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
run() { echo; echo "\$ $*"; "$@" 2>&1 | head -${LINES_MAX:-40}; echo "[exit=${PIPESTATUS[0]}]"; }
PY=$(uv python find)
nohup $PY /h/fake_ollama.py >/tmp/fake_ollama.out 2>&1 &
sleep 1
export V="/mnt/c/Users/Ruben Melo/Documents/Obsidian/my vault"
sb init --vault "$V" --model local --language en --no-obsidian --nightly none --no-ocr 2>&1 | head -3
BODY='A harness is the code layer that manages context, memory and the verification of results for an AI agent. The harness runs the tools and checks every step before the agent goes on. This clipping is long enough to be read in one go by the model.'
mkdir -p ~/clips
mk() { printf -- "---\ntitle: '%s'\nsource: \"https://example.org/%s\"\n---\n%s Unique id %s.\n" "$2" "$1" "$BODY" "$1" > ~/clips/$1.md; }
mk c1 "Foo"; mk c2 "foo"; mk c3 "Café"; mk c4 "$($PY -c 'print("日本語"*30)')"; mk c5 "CON"; mk c6 "Trailing dots..."; mk c7 "$($PY -c 'print("L"*300)')"; mk c8 "$($PY -c 'print("🚀"*100)')"
run sb add ~/clips/*.md
run sb run
ls "$V/wiki/sources" | cut -c1-80
run sb lint
run sb status
(cd "$V" && git log --oneline | head -3; git status --short | head -3)
mkdir -p ~/lk; echo "flock on vfat:"; flock -n "$V/.esbi/run.lock" -c 'echo got lock; flock -n "$V/.esbi/run.lock" -c "echo second ok" || echo "second blocked (expected)"'
EOS
su tester -c "bash /tmp/inner.sh"
