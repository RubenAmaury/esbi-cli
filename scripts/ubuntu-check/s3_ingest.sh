#!/bin/bash
# Step 3: real ingest with the fake Ollama. Needs APT="git" (vault history on, fresh user with NO git identity).
. /h/pre.sh
PY=$(uv python find)
nohup $PY /h/fake_ollama.py >/tmp/fake_ollama.out 2>&1 &
sleep 1
sh_ 'curl -s localhost:11434/api/version'
echo "git: $(git --version)  identity: [$(git config --global user.name)] [$(git config --global user.email)]"
sh_ 'sb init --vault ~/vault --model local --language en --no-obsidian --nightly none --no-ocr'
cat > ~/notes.txt <<'X'
plain text file
X
cat > ~/clip.md <<'X'
---
title: "A clipped article about harnesses"
source: "https://example.org/harness"
author:
  - "[[Someone]]"
published: 2026-09-01
created: 2026-10-05
tags:
  - clippings
---
A harness is the code layer that manages context, memory and the verification of results for an AI agent. The harness runs the tools and checks every step before the agent goes on. This clipping is long enough to be read in one go by the model, and it mentions Anthropic as an example of a company that publishes harness designs for agents.
X
sh_ 'sb add ~/notes.txt'
sh_ 'sb add ~/clip.md /h/pdfs/plain-text.pdf /h/pdfs/twelve-pages.pdf /h/pdfs/attention.pdf /h/pdfs/scan-1page.pdf'
sh_ 'sb add https://en.wikipedia.org/wiki/Zettelkasten'
sh_ 'sb add http://localhost:8000/x http://127.0.0.1/ "http://[::1]/" http://169.254.169.254/ http://172.17.0.1/'
sh_ 'sb status'
run sb doctor
sh_ 'time sb run 2>&1 | grep -v -E "^(\*\*\*|Run|  git config|to set|Omit|fatal: unable|$)"'
sh_ 'sb status --json'
sh_ 'cd ~/vault && ls -R wiki | head -50; git log --oneline | head; git status --short | head'
sh_ 'head -40 ~/vault/wiki/sources/*lipped*.md'
sh_ 'sb ask "What does the harness do?"'
sh_ 'sb ask "What does the harness do?" --json'
sh_ 'sb lint'
sh_ 'sb export --out ~/site 2>&1; ls ~/site | head; sb export --help | head -20'
sh_ 'sb doctor --json | head -c 1500'
sh_ 'sb status --json'
sh_ 'cat /tmp/fake_ollama.out | tail -5'
