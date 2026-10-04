#!/usr/bin/env bash
# A throwaway CA and a server certificate for the IMAP integration test (compose profile `imap`).
# Writes .imap-test/ca.pem (what the test trusts) and .imap-test/keystore.p12 (what the server
# presents). Nothing here is a secret: the keys only ever sign a mail server that holds test data.
# Production code never trusts this CA: the test points SSL_CERT_FILE at it for one process.
set -euo pipefail
cd "$(dirname "$0")/.."
out=.imap-test
mkdir -p "$out"
cd "$out"

cat >server.ext <<'EXT'
subjectAltName = DNS:localhost, DNS:imap, IP:127.0.0.1
extendedKeyUsage = serverAuth
basicConstraints = CA:FALSE
EXT

openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=esbi-cli test CA" \
  -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -keyout ca.key -out ca.pem 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=localhost" -keyout server.key -out server.csr 2>/dev/null
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days 30 \
  -extfile server.ext -out server.pem 2>/dev/null
openssl pkcs12 -export -in server.pem -inkey server.key -certfile ca.pem -name greenmail \
  -out keystore.p12 -passout pass:changeit
chmod 644 ca.pem keystore.p12
rm -f server.csr server.ext ca.srl
echo "Wrote $out/ca.pem and $out/keystore.p12"
