# Safety and privacy

What the worker can and cannot do to your files, and what leaves your machine.

## What leaves your machine

| You choose | What is sent, and to whom |
|---|---|
| A local model (Ollama, LM Studio on this machine) | Nothing |
| Your Claude subscription (`claude-cli`) | The text of each source goes to Anthropic, through the official `claude` tool |
| An API key (`anthropic`, `openai`-compatible) | The text of each source goes to that provider |
| Ollama or LM Studio on **another machine** (`base_url`), or an Ollama `-cloud` model | The text goes to that host. It is not "local" even though the program is |

In plain words: a model **sends text out** when someone other than you runs it. Every model in the worker carries that flag (it is what the privacy rules read). Local Ollama and local LM Studio do not send text out; the API providers and `claude-cli` do; a `fallback` follows the model that sees the text first, so a local main model with a cloud fallback counts as sending out. An Ollama or LM Studio model whose `base_url` is not this machine (anything but `localhost`, `127.x` or `::1`) counts as sending text out: `sb doctor` shows a `WARN server <task>` line for each such model, and `sb init --base-url` or the installer's server-address question prints the same warning.

Nothing else is sent anywhere: there is no telemetry and no account. The worker fetches the web pages you ask for, and talks to Gmail only if you turn mail capture on.

## Email stays local

Email is private by design. **Email is never shown to a model that sends text out.** This is enforced in three places:

1. **Writing.** An email is written only by `[llm.private]`, which must be a model on this machine. Without one, an email is refused while a cloud model is set (`sb doctor` warns beforehand). A remote `[llm.private]` is refused too.
2. **Context.** When a cloud model writes any other source, email pages, and concept pages built only from email, are left out of the existing-pages list it sees. A page that email helped write is offered by title only, without its one-line summary.
3. **Questions.** `sb ask` with a cloud model leaves out email pages and the `## From [[email]]` sections of shared pages (`## Desde` in a Spanish vault: both are recognised), and any saved answer that used an email page.

A PDF attached to an email counts as email, and so does text read by OCR from a scanned PDF that came attached to one. An embedding model that is not on this machine never receives email-derived pages, and an email being ingested is never used as a query to it.

To set it up, see [Keep email local](../how-to/email.md#keep-email-local).

## Files and history

- The model **never writes files** and needs no tool access; the worker applies only what passes validation.
- Nothing is deleted. Mail is read with `BODY.PEEK` and never removed; `raw/` is never modified; the old vault is only read. `sb reingest` replaces notes, but tags the vault in git first.
- The mailbox password lives only in the macOS Keychain, never in a file, a log or the command line.
- Notes made from email are ordinary notes in the vault. They go wherever the vault goes: the git backup remote (`sb init --remote`, pushed after each index refresh; use a **private** repository) and the `sb export` website (do not publish that folder if you capture email). `raw/` is never exported.
- Text a source puts into a note (a page, a mail, a model's answer) is plain text there: HTML is shown as text, images in model text are dropped, and the exported site runs no scripts of its own.

## Fetching

- `http`/`https` only, public addresses only (localhost, private ranges, link-local and cloud-metadata addresses are refused), re-checked on every redirect. The name is resolved once per request and the connection goes to the address that was checked (the `Host` header and the TLS name stay the original host, so certificates are still verified), so a DNS server cannot answer "public" to the check and "private" to the connection.
- Downloads are capped at 20 MB and 120 seconds.
- If you set `HTTP_PROXY`/`HTTPS_PROXY`, the proxy is sent that checked address too, but it is still a machine you trust: a proxy inside your network can reach internal hosts by design, and `NO_PROXY` entries written as host names no longer match.
- The IMAP connection verifies the server's certificate and name.
- A `config.toml` in the current folder is never read: a cloned repository could otherwise point the model or the mailbox at someone else's server.

## Prompt injection

The text of a source is passed to the model inside delimiters with an instruction to treat it as data; that reduces, but does not eliminate, prompt-injection risk from hostile pages or emails. What the model can do with a hostile instruction is limited by design: it can only return a plan that is validated, and every claim in it (quotes, terms, entities, links) is checked against the source before anything is written.

## Images

Images and scanned PDFs are read by `[llm.ocr]`, which only accepts an Ollama model running on this machine: an image is never sent to a cloud model, even when the notes are written by one. The text read from an image is as untrusted as a web page (an image can carry written instructions); the same delimiters apply.

## Reporting a problem

Please report vulnerabilities privately: see [SECURITY.md](https://github.com/RubenAmaury/esbi-cli/blob/main/.github/SECURITY.md).
