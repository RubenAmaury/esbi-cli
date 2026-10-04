# Security policy

## Supported versions

Only the latest 0.x release is supported. Please update before reporting.

## Reporting a vulnerability

**Do not open a public issue for a security problem.** Use GitHub's private reporting: on the repository page, choose *Security* → *Report a vulnerability*. Include the version (`sb version`), what you did, and what you saw. You will get a reply within a few days; this is a solo project, so a fix may take longer, but you will be told where it stands.

## What the app is designed to protect

- **Your files**: the language model never touches files; it returns JSON that is validated, then written by the program. `raw/` (the originals) is never modified.
- **Fetching**: only `http(s)` URLs on public addresses are fetched, and every redirect hop is checked (the guard in `src/esbi_cli/netguard.py`). The name is resolved once per hop and the connection goes to the address that was checked, so a DNS answer cannot change between the check and the connection (DNS rebinding).
- **Untrusted text**: web pages, PDFs and emails are delimited as data in every prompt, and what the model claims is checked against the source (quotes, glossary terms, entities, links) before anything is written. A prompt injection in a source can still make a note say something wrong; it cannot make the program run a command or write outside the vault.
- **Credentials**: the mailbox app password is stored in the macOS Keychain, never in a file or on a command line; the app only reads mail and never deletes it.
- **Email and cloud models**: email is read only by a local model, and cloud models are never shown email pages.

## Out of scope

The security of the model provider you choose, of your Obsidian vault folder's sync service, and of a machine you do not control.
