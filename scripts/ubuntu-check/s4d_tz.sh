#!/bin/bash
# Step 4d: the 03:00 due logic under different time zones (needs APT="tzdata faketime"), plus a cron-like minimal environment.
. /h/pre.sh
PY=$(uv python find)
nohup $PY /h/fake_ollama.py >/tmp/fake_ollama.out 2>&1 &
sleep 1
sb init --vault ~/v --model local --language en --no-obsidian --nightly 03:00 --no-ocr >/dev/null
export ESBI_CONFIG=~/.config/esbi-cli/config.toml
grep -n nightly_time $ESBI_CONFIG
n=0
runs() { wc -l < ~/v/.esbi/runs.jsonl 2>/dev/null || echo 0; }
tick() { # tick <local datetime> : one hourly cron tick at that local time; says whether a run started
  n=$((n+1)); printf -- "---\ntitle: 'Item %s'\n---\nA harness is the code layer that manages context, memory and the verification of results for an AI agent. The harness runs the tools and checks every step. Unique %s.\n" $n $n > ~/c$n.md
  sb add ~/c$n.md >/dev/null
  before=$(runs)
  out=$(faketime "$1" sb run --if-due 2>&1 | grep -E "ingested|Another|nothing|not due|due" | head -2)
  after=$(runs)
  echo "  [$TZ] $1 -> runs.jsonl lines $before -> $after  | $out"
}
for tz in UTC America/Bogota Pacific/Auckland America/New_York; do
  echo "##### TZ=$tz"; export TZ=$tz
  rm -f ~/v/.esbi/runs.jsonl
  echo "date check: $(faketime '2026-10-06 03:05:00' date '+%F %T %Z')"
  tick '2026-10-05 02:30:00'   # before 03:00: yesterday's boundary
  tick '2026-10-06 02:59:00'
  tick '2026-10-06 03:01:00'   # first tick after 03:00: runs
  tick '2026-10-06 04:01:00'   # already ran since 03:00: skipped
  tick '2026-10-07 02:59:00'   # still before the next boundary: skipped
  tick '2026-10-07 03:00:00'   # boundary: runs
  echo "  last record:"; tail -1 ~/v/.esbi/runs.jsonl | cut -c1-200
done
echo "##### DST spring-forward day (America/New_York, 2026-03-08: 02:00 -> 03:00)"
export TZ=America/New_York; rm -f ~/v/.esbi/runs.jsonl
tick '2026-03-08 01:30:00'; tick '2026-03-08 03:00:00'; tick '2026-03-08 04:00:00'
echo "##### cron-like minimal environment (env -i), absolute path, no LANG, no TZ"
unset TZ
sh_ 'env -i HOME=$HOME PATH=/usr/bin:/bin sb version'
sh_ 'env -i HOME=$HOME PATH=/usr/bin:/bin /bin/sh -c "sb version"'
sh_ 'env -i HOME=$HOME PATH=/usr/bin:/bin $HOME/.local/bin/sb run --if-due --config $HOME/.config/esbi-cli/config.toml'
sh_ 'env -i HOME=$HOME PATH=/usr/bin:/bin $HOME/.local/bin/sb status --json --config $HOME/.config/esbi-cli/config.toml | head -c 200'
