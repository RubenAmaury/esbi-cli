#!/bin/bash
# Step 4g: email password with a REAL secret service (gnome-keyring over a private D-Bus session), as on Ubuntu desktop.
. /h/pre.sh
sb init --vault ~/v --model local --language en --no-obsidian --nightly none --no-ocr >/dev/null
sb email configure --user someone@example.test >/dev/null
sed -i 's/^imap_host = .*/imap_host = "127.0.0.1"/' ~/.config/esbi-cli/config.toml
grep -n -A4 "^\[email\]" ~/.config/esbi-cli/config.toml
cat > /tmp/inner.sh <<'EOS'
export PATH=$HOME/.local/bin:$PATH NO_COLOR=1
echo -n "testpass" | gnome-keyring-daemon --unlock --components=secrets >/dev/null 2>&1
echo '$ echo "abcd efgh ijkl mnop" | sb email set-password --stdin'
echo "abcd efgh ijkl mnop" | sb email set-password --stdin 2>&1 | tail -4
echo '$ sb doctor | grep email'
sb doctor 2>&1 | grep -i -E "email"
echo '$ sb email fetch (imap_host 127.0.0.1: nothing listens)'
sb email fetch 2>&1 | tail -3
echo '$ python keyring check'
secret-tool search service esbi-cli-imap 2>&1 | head -5 || true
EOS
dbus-run-session -- bash /tmp/inner.sh
echo "##### second session without unlocked keyring / without D-Bus"
sh_ 'sb email fetch'
sh_ 'env -u DBUS_SESSION_BUS_ADDRESS sb doctor | grep -i email'
