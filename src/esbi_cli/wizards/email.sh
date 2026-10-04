#!/usr/bin/env bash
#
# Wizard: connect esbi-cli to a dedicated Gmail mailbox (label + app password).
# Generated with the /wizard skill; run it with: sb setup email
#
# Everything above the "STAGES" marker is the wizard library: do not hand-edit
# it. Author the per-step stages below the marker.

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────
# Wizard library: delightful, consistent UX, identical across every wizard.
# ──────────────────────────────────────────────────────────────────────────

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
  BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
  BLUE=$(tput setaf 4); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3); RED=$(tput setaf 1)
else
  BOLD=""; DIM=""; RESET=""; BLUE=""; GREEN=""; YELLOW=""; RED=""
fi

# Author sets this at the top of the stages section.
TOTAL_STAGES=0

_STAGE_INDEX=0
ENV_FILE="${ENV_FILE:-.env}"
WRITTEN_ENV=()    # KEYs written to ENV_FILE this run
WRITTEN_SECRET=() # secret NAMEs set this run
SKIPPED=()        # things we couldn't do (e.g. gh missing)

# _clear wipes the terminal so only the current step is on screen. No-op when
# output isn't a terminal, so piped logs stay readable.
_clear() {
  [[ -t 1 ]] || return 0
  if command -v tput >/dev/null 2>&1; then tput clear; else printf '\033[2J\033[3J\033[H'; fi
}

# banner "Title" shows the opening frame: what this wizard does.
banner() {
  _clear
  printf '\n%s%s  %s%s\n' "$BOLD" "$BLUE" "$1" "$RESET"
  printf '%s  %s stages%s\n\n' "$DIM" "$TOTAL_STAGES" "$RESET"
  printf '%s  You drive the browser; this wizard tells you exactly what to do and\n' "$DIM"
  printf '  captures the values you copy back. Stop any time with Ctrl-C and re-run\n'
  printf '  later, since it remembers values already saved.%s\n' "$RESET"
  pause "Ready to start?"
}

# stage "Name" clears the screen, then announces a stage and shows progress.
# Clearing keeps only the current step on screen.
stage() {
  _clear
  _STAGE_INDEX=$((_STAGE_INDEX + 1))
  printf '\n%s%s▸ Stage %s/%s · %s%s\n' \
    "$BOLD" "$BLUE" "$_STAGE_INDEX" "$TOTAL_STAGES" "$1" "$RESET"
}

# say "..." prints a plain instruction line.
say()  { printf '  %s\n' "$1"; }
# step "..." is a numbered-feeling action the human takes in the browser.
step() { printf '  %s•%s %s\n' "$BLUE" "$RESET" "$1"; }
note() { printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; }
warn() { printf '  %s⚠ %s%s\n' "$YELLOW" "$1" "$RESET"; }

# open_url URL opens it in the human's browser, cross-platform incl. WSL.
open_url() {
  local url="$1"
  printf '  %s↗ opening%s %s\n' "$GREEN" "$RESET" "$url"
  { if   command -v wslview     >/dev/null 2>&1; then wslview "$url"
    elif command -v explorer.exe >/dev/null 2>&1; then explorer.exe "$url"
    elif command -v xdg-open    >/dev/null 2>&1; then xdg-open "$url"
    elif command -v open        >/dev/null 2>&1; then open "$url"
    else warn "couldn't open a browser; visit it manually: $url"; fi
  } >/dev/null 2>&1 || warn "couldn't open a browser, so visit it manually: $url"
}

# pause "msg" waits for the human to confirm they've done the manual part.
pause() {
  printf '  %s%s%s ' "$DIM" "${1:-Press Enter to continue}" "$RESET"
  read -r _ || true
}

# confirm "question" is a y/N gate; returns success on yes.
confirm() {
  local reply=""
  printf '  %s? %s [y/N] ' "$YELLOW" "$1"
  read -r reply || true
  [[ "$reply" =~ ^[Yy] ]]
}

# _existing KEY: current value of KEY in ENV_FILE, if any.
_existing() {
  [[ -f "$ENV_FILE" ]] || return 1
  local line; line=$(grep -E "^${1}=" "$ENV_FILE" | tail -n1) || return 1
  printf '%s' "${line#*=}"
}

# ask KEY "Prompt" reads a value into $KEY. Offers the existing .env value as
# a default on re-runs (Enter keeps it). Visible input (non-secret).
ask() {
  local key="$1" prompt="$2" current input
  current=$(_existing "$key" || true)
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  read -r input || true
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

# ask_secret KEY "Prompt" is like ask, but input is hidden.
ask_secret() {
  local key="$1" prompt="$2" current input
  current=$(_existing "$key" || true)
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  read -rs input || true
  printf '\n'
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

# write_env KEY VALUE upserts KEY=VALUE into ENV_FILE (creates it; replaces
# any existing line). Idempotent.
write_env() {
  local key="$1" value="$2" tmp
  touch "$ENV_FILE"
  tmp=$(mktemp)
  grep -vE "^${key}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
  WRITTEN_ENV+=("$key")
  printf '  %s✓ wrote%s %s → %s\n' "$GREEN" "$RESET" "$key" "$ENV_FILE"
}

# set_secret NAME VALUE sets a GitHub Actions repo secret via gh. Falls back
# to a warning (and records it) if gh is unavailable or unauthenticated.
set_secret() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if printf '%s' "$value" | gh secret set "$name" >/dev/null 2>&1; then
      WRITTEN_SECRET+=("$name")
      printf '  %s✓ set%s GitHub secret %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub secret $name (set it manually: gh secret set $name)")
  warn "skipped GitHub secret $name: gh not ready; set it later"
}

# set_var NAME VALUE sets a GitHub Actions repo variable (non-secret).
set_var() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if gh variable set "$name" --body "$value" >/dev/null 2>&1; then
      printf '  %s✓ set%s GitHub variable %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub variable $name")
  warn "skipped GitHub variable $name, gh not ready; set it later"
}

# finish clears, then shows a closing summary of everything configured.
finish() {
  _clear
  printf '\n%s%s  ✓ Setup complete%s\n' "$BOLD" "$GREEN" "$RESET"
  (( ${#WRITTEN_ENV[@]} ))    && note "wrote ${#WRITTEN_ENV[@]} value(s) to $ENV_FILE: ${WRITTEN_ENV[*]}"
  (( ${#WRITTEN_SECRET[@]} )) && note "set ${#WRITTEN_SECRET[@]} GitHub secret(s): ${WRITTEN_SECRET[*]}"
  if (( ${#SKIPPED[@]} )); then
    printf '\n'; warn "still to do by hand:"
    for s in "${SKIPPED[@]}"; do note "  - $s"; done
  fi
  printf '\n'
}

# ──────────────────────────────────────────────────────────────────────────
# STAGES
# ──────────────────────────────────────────────────────────────────────────

# Run through `sb setup email`, which sets SB (the sb command), SB_CONFIG and SB_TEMPLATES.
SB="${SB:-sb}"
CONFIG="${SB_CONFIG:?run this wizard with: sb setup email}"
ENV_FILE=/dev/null                # this wizard writes config.toml + the Keychain, not a .env
LABEL="esbi-cli"               # must match [email].mailbox in config.toml

TOTAL_STAGES=6

banner "esbi-cli: connect a Gmail mailbox (optional)"
say "Not needed for the basics: you can always add PDFs and links with 'sb add' or by dropping them in inbox/."
say "This lets you forward an email to your own address and have it become a note."
say "Press Ctrl-C at any time to stop; nothing is changed until stage 5."
pause "Continue?"

# ── 1 ─────────────────────────────────────────────────────────────────────
stage "Turn on 2-Step Verification"
say "Google only offers app passwords on accounts with 2-Step Verification."
open_url "https://myaccount.google.com/security"
step "Under 'How you sign in to Google', check that 2-Step Verification is On."
step "If it is Off, turn it on and finish Google's prompts."
pause "2-Step Verification is on? Press Enter."

# ── 2 ─────────────────────────────────────────────────────────────────────
stage "Create the Gmail label"
say "esbi-cli reads one label. Mail you want to capture ends up under it."
open_url "https://mail.google.com/mail/u/0/"
step "In the left sidebar choose 'Create new label' (under 'More' > Labels if hidden)."
step "Name it exactly: $LABEL"
pause "Label '$LABEL' created? Press Enter."

# ── 3 ─────────────────────────────────────────────────────────────────────
stage "Route forwarded mail into the label"
ask EMAIL_ADDRESS "Your Gmail address (e.g. you@gmail.com):"
[[ "$EMAIL_ADDRESS" == *@* ]] || { warn "that does not look like an email address"; exit 1; }
[[ "$EMAIL_ADDRESS" == *@gmail.com || "$EMAIL_ADDRESS" == *@googlemail.com ]] \
  || warn "this wizard assumes Gmail; other providers need their own IMAP host and label"
PLUS_ADDRESS="${EMAIL_ADDRESS%@*}+esbi-cli@${EMAIL_ADDRESS#*@}"
say ""
say "Anything you forward to this address lands in your own inbox:"
printf '  %s%s%s\n\n' "$BOLD" "$PLUS_ADDRESS" "$RESET"
open_url "https://mail.google.com/mail/u/0/#settings/filters"
step "Click 'Create a new filter'."
step "In the 'To' field enter: $PLUS_ADDRESS   then 'Create filter'."
step "Tick 'Apply the label' and pick '$LABEL'."
step "Also tick 'Skip the Inbox (Archive it)' so you never open these mails by accident."
note "The worker reads the label's last 14 days, read or unread, and skips what it already saved."
step "Click 'Create filter'."
pause "Filter created? Press Enter."

# ── 4 ─────────────────────────────────────────────────────────────────────
stage "Create an app password"
say "A separate password just for esbi-cli; you can revoke it any time."
open_url "https://myaccount.google.com/apppasswords"
step "Name the app 'esbi-cli' and click Create."
step "Copy the 16-character password Google shows."
note "Don't paste it here: the next stage stores it straight into your Keychain."
pause "Password copied? Press Enter."

# ── 5 ─────────────────────────────────────────────────────────────────────
stage "Save the settings and the password"
"$SB" email configure --user "$EMAIL_ADDRESS" --label "$LABEL" --config "$CONFIG"
printf '  %s✓ wrote%s [email] settings → %s\n' "$GREEN" "$RESET" "$CONFIG"
say "Now paste the app password (it stays hidden and goes only into the Keychain):"
"$SB" email set-password --config "$CONFIG"

# ── 6 ─────────────────────────────────────────────────────────────────────
stage "Test it end to end"
step "Forward any email to $PLUS_ADDRESS (or send one to yourself at that address)."
step "In Gmail, check it shows up under the '$LABEL' label."
pause "Mail is under the label? Press Enter to fetch it."
if "$SB" email fetch --config "$CONFIG"; then
  say ""
  say "If it says 'Mail: 1 saved', it works: the mail is now in the vault's inbox/ and"
  say "the next 'sb run' turns it into a note."
else
  warn "the fetch failed; the message above says why (wrong app password? label name?)."
  SKIPPED+=("mail test: fix the error above, then run: sb email fetch")
fi

finish
