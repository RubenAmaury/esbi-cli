# Capture email

Forward an article, a newsletter or a PDF to yourself and get a note. It is optional and built for Gmail. Everything about mail is read-only: the worker only peeks at messages and cannot delete them.

## What you need

- A Gmail account with 2-Step Verification on (Google only offers app passwords then).
- A Mac: the password is kept in the macOS Keychain. (Email capture on Linux is untested; see [Install](install.md#linux).)
- A model on your machine for email, because email is never shown to a model that sends text away: see [Keep email local](#keep-email-local).

## Set it up with the wizard

```bash
sb setup email
```

It walks you through six stages, telling you exactly what to click, and writes the settings for you:

1. Check that 2-Step Verification is on.
2. Create a Gmail label named `esbi-cli`.
3. Create a Gmail filter: mail to `you+esbi-cli@gmail.com` gets the label and skips the inbox, so these mails never mix with your own.
4. Create an app password called `esbi-cli`, and copy it.
5. Save the settings, then paste the password: it is typed hidden and goes straight into the Keychain, never through the wizard, never into a file.
6. Test it: forward a mail to that address, and the wizard fetches it.

You can stop with Ctrl-C and run it again; nothing changes until stage 5. If you prefer to do it by hand:

```bash
sb email configure --user you@gmail.com
```

```
Mail capture on for you@gmail.com, label esbi-cli, in ~/.config/esbi-cli/config.toml
```

```bash
sb email set-password
```

```
App password for you@gmail.com:
Saved to the Keychain.
```

The first writes the `[email]` block of the config; the second prompts for the app password (hidden). `pbpaste | sb email set-password --stdin` pastes it without typing. Spaces in the password Google shows are dropped.

## Use it

Forward anything to `you+esbi-cli@gmail.com`. The next `sb run` (or the nightly job) turns it into a note. To fetch right away:

```bash
sb email fetch
```

```
Mail: 2 saved, 0 duplicates, 0 failed.
```

What happens:

- The worker reads the label's last 14 days, whether you opened the mails or not, and skips any it already saved (by Message-ID). It marks a mail as seen only after its note is written.
- Each mail becomes a Markdown file in `inbox/`, then a note like any other source, with `kind: email`.
- A **PDF attached** to a mail is saved in `inbox/` too, and becomes its own note.
- Blank "padding" characters that newsletters add to their preview text are removed.
- Links inside a mail are not followed: the mail body is the source.
- A mail that cannot be read is reported once (`Mail: ... 1 failed`) and then skipped; its id is kept in `.esbi/mail-failed.txt`.
- Nothing is ever deleted from your mailbox.

## Keep email local

Email is private by design. A model that **sends text out** (an API, your Claude subscription, an Ollama or LM Studio server on another machine) is never shown email. With a local model you need do nothing. If any of your models is a cloud kind, add a local one for email:

```toml
[llm.private]
model = "ollama/llama3.2:latest"
```

`sb init --model subscription` or `--model api` writes it for you. With it, three things hold:

1. An email is written only by `[llm.private]`. Without it, an email is refused with `an email cannot be written by a model that sends text away: add a local model as [llm.private] in config.toml`.
2. When a cloud model writes any other source, pages made from email, and concept pages built only from email, are left out of what it sees.
3. `sb ask` with a cloud model leaves out email pages and the email sections of shared pages.

`sb doctor` shows where you stand:

```
  ok   email privacy: email is read only by a model on this machine
```

or `WARN email privacy: ... send text away and no [llm.private] is set: emails will be refused`, or `FAIL email privacy: [llm.private] (or its fallback) sends text away`. Notes made from email are ordinary notes in the vault, so they go wherever the vault goes: the git remote, and the `sb export` site. Use a private remote and do not publish an export. Details: [Safety and privacy](../explanation/safety-and-privacy.md#email-stays-local).

## When something goes wrong

| Message | Cause and fix |
|---|---|
| `error: email is disabled: set [email].enabled = true in config.toml` | Mail capture is off: run `sb email configure --user ...` |
| ``No IMAP password in the Keychain for you@gmail.com. Store it with `sb email set-password`.`` | Run `sb email set-password` |
| `IMAP login/select failed for you@gmail.com@imap.gmail.com: ...` | Wrong app password (not your normal password), or the account lacks 2-Step Verification. Create a new app password and store it again |
| `Mailbox 'esbi-cli' not found on imap.gmail.com` | The Gmail label is missing or named differently; fix it, or `[email].mailbox` |
| `The Keychain is waiting for permission: a dialog on the Mac asks...` | Click *Always Allow* on the macOS dialog, or store the password again |
| `Could not write to the Keychain: ...` with `The old item belongs to another program` | Run the `security delete-generic-password -s esbi-cli-imap -a you@gmail.com` it prints, then `sb email set-password` |
| `warning: mail skipped: ...` during `sb run` | Mail never stops a run: the rest was processed. Run `sb email fetch` to see the same error alone |

More in [Troubleshooting](troubleshooting.md).
