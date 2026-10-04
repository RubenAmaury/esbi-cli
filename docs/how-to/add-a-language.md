# Add a language for the notes

The notes can be written in English (`en`) or Spanish (`es`). Adding another language is a data-only change: one entry in one file, no logic. This page is for a contributor who works from a copy of the source code; if you only want to choose between the two languages that exist, see [Language of the notes](../reference/configuration.md#language-of-the-notes).

The command line itself (messages, `--help`, errors) and the documentation stay English whatever language the notes are in.

## What you change

Everything the program writes into the wiki, and everything it tells the model about the language, lives in the `LANGUAGES` dictionary in `src/esbi_cli/lang.py`. Nothing else in the code names a language.

1. Copy the whole `"en"` entry and change its key to the language's code (`"fr"`, `"pt"`...). The code is what a user writes in `[notes].language`.
2. Translate the values. Leave the keys and the `{placeholders}` as they are: a label may be reordered, but each `{name}` must appear once, because the program fills it in.

| Field | What it is | If you leave it empty |
|---|---|---|
| `name` | The language's name in English, as the instruction to the model uses it (`Write ALL text in French`) | Required |
| `hint` | One more sentence appended to the instruction, for a language a small model needs help with. Add it only if a measurement shows a problem | Nothing is added |
| `relation_examples` | Short labels for how two ideas relate, written as the model should write them | Required: the model copies this style |
| `stopwords` | About twenty of the language's most frequent words, separated by spaces, to notice an answer in the wrong language | The check is skipped: an answer in the wrong language is accepted. The worker never guesses |
| `placeholders` | How a small model that copies the prompt's wording starts a summary ("Executive summary of ...") | Required, but a short guess is fine |
| `ask_example`, `rewrite_example` | A worked answer to show the model the exact format for `sb ask` and for the question rewrite. Written in the new language: a small model imitates it | Required |
| `labels` | Every heading and sentence written into the wiki: the sections of a note, the daily index, the lint and benchmark reports, the refusals of `sb ask` | Required, all of them |

## Check it

```bash
uv run pytest tests/test_lang.py
```

This fails if your entry lacks a key that `en` has, or if a label has different `{placeholders}` than the English one. Then try it on real material with a scratch vault (never your own):

```bash
sb init --vault /tmp/try --config-file /tmp/try.toml --language fr
sb add https://en.wikipedia.org/wiki/Zettelkasten --config /tmp/try.toml
sb run --config /tmp/try.toml
```

`sb init --language` accepts any code in `LANGUAGES`, and the error for a code that is not there lists the supported ones. Read the note: the headings, the daily index and the language of the prose. Then run `sb bench` on a few sources and look at the **right language** column: with the model you use, it should be 100% on the first try. If a small model keeps answering in the source's language, add a `hint`.

## What you do not need to do

- **Teach the readers.** A vault written in one language and read after switching to another still works: the privacy filters, `sb ask`, the read ticks and `sb reingest` recognise the headings of every language in `LANGUAGES`.
- **Change the prompts.** They are in English for every language; only the language named in them changes.
- **Rewrite old notes.** The worker never does. `sb reingest --all` rebuilds them in the new language.
