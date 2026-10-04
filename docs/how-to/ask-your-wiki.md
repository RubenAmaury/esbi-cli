# Ask your wiki

`sb ask` answers a question from your own notes and cites them. It never answers from the model's general knowledge: when your notes do not cover the question, it says so.

## Ask a question

```bash
sb ask "What is the forgetting curve and how does it relate to notes?"
```

```
The forgetting curve describes the rate at which learned material is forgotten unless reviewed [[Forgetting Curve]]. It suggests that most learned material is forgotten within days unless reviewed.

Sources: [[Spaced Repetition]], [[Forgetting Curve]]
```

The `Sources:` line names the notes the answer rests on. Only citations that point at a real page are kept: a link the model invented is printed as plain text. Ask in any language; the answer is in the language of your notes (`[notes].language`).

When nothing in the wiki answers it:

```bash
sb ask "Who painted the Mona Lisa?"
```

```
I find nothing about this in the wiki.
```

This is deliberate: an answer with no verifiable citation is refused. If you expected an answer, try the words your notes use, or see [Troubleshooting](troubleshooting.md#sb-ask-finds-nothing-but-you-expect-an-answer).

How long it takes depends on the model: seconds with a subscription or an API, up to a minute or two with a small local model. The question is answered by `[llm.ask]` if you set one, else by `[llm.summarize]`.

## Keep a good answer

Add `--save`:

```bash
sb ask "What is the forgetting curve and how does it relate to notes?" --save
```

```
The forgetting curve is the rate at which memorized material is lost over time [[Forgetting Curve]]. It was studied by Hermann Ebbinghaus [[Hermann Ebbinghaus]], who measured the forgetting curve in his experiments [[Spaced Repetition]]. The Spaced Repetition paper concludes that spacing reviews beats cramming and provides a cheap form of spaced repetition with almost no effort.

Sources: [[Forgetting Curve]], [[Hermann Ebbinghaus]], [[Spaced Repetition]]
Saved wiki/syntheses/What is the forgetting curve and how does it relate to notes.md
```

The answer becomes a page in `wiki/syntheses/`, named after your question (cut at about 80 characters), listing the pages it came from, and the vault gets a git commit. Answers are only saved when you ask, and only when they are grounded. A refused answer is never saved.

## Find notes whose words differ from your question

Retrieval has two sides. The keyword side looks for the question's words in titles, aliases and text. It misses a note when the question and the note use different words ("juez LLM" against a note titled "JEV-as-a-Judge") or another language. Two optional settings fix that.

**Rewrite the question.** One small extra model call turns the question into search words in both languages:

```toml
[run]
rewrite_questions = true
```

**Search by meaning.** See below.

## Search by meaning

An embedding model adds a second search that compares meaning, not words ("hybrid search"). Turn it on once:

```bash
ollama pull nomic-embed-text
```

```toml
[llm.embed]
model = "ollama/nomic-embed-text"
timeout_seconds = 60
```

```bash
sb doctor
```

`sb doctor` checks that the embedding model is installed. The first `sb ask` or `sb run` afterwards embeds every page, once, section by section (about 14 seconds for 175 pages on a Mac), and stores the vectors in `.esbi/index.sqlite3`. After that only pages that change are embedded again, and a question costs one small extra call. It also helps find related pages while a new source is written.

On the author's vault of 175 pages, with 16 questions, the right page was in the top 6 for 88% with keywords alone and 94% with hybrid search, and it ranked higher (MRR 0.68 to 0.82). The method and the numbers are in [Retrieval and RAG](../explanation/rag-fit.md#hybrid-retrieval-built-m20); measure it on your own notes with `sb eval`, below.

On a four-question test vault, the same `sb eval` that gave `MRR 0.44` with keywords gave this with hybrid search on:

```
Retrieval on 4 questions: recall@6 75% (3/4), MRR 0.62
  miss: How do I cook rice? (expected Arroz; got Arno Schmidt, Zettelkasten, Spaced Repetition, Spaced Repetition y Note-Taking, Active recall versus rereading, Spaced Repetition y Note-Taking (2))
```

Note the miss: a search by meaning always returns its nearest pages, so an unanswerable question still reaches the model. It must cite a page that exists, or the answer is refused.

- Off by default. With the section absent, or Ollama unreachable, search is exactly the keyword search; when it is unreachable you see `warning: embeddings unavailable (...); searching by keyword only`.
- Only Ollama models can embed (`ollama/<name>`).
- If the embedding model is not on this machine, email pages are never sent to it.
- Changing the model discards the old vectors and embeds again.

## Measure retrieval with `sb eval`

Before and after you change anything about search, measure it. `sb eval` scores the step where `sb ask` picks the pages the model will read, on questions whose source you know. It needs no model call (unless you ask for one) and takes about a second.

Make `.esbi/golden.jsonl` in your vault: one JSON object per line, a question and the start of the title(s) of the note(s) that should answer it. A long source title can be cut:

```json
{"question": "What is a Zettelkasten?", "expect": ["Zettelkasten"]}
{"question": "How does spaced repetition help you remember?", "expect": ["Spaced Repetition"]}
{"question": "Who described the forgetting curve?", "expect": ["Hermann Ebbinghaus", "Forgetting Curve"]}
{"question": "How do I cook rice?", "expect": ["Arroz"]}
```

```bash
sb eval
```

```
Retrieval on 4 questions: recall@6 75% (3/4), MRR 0.44
  miss: How do I cook rice? (expected Arroz; got nothing)
```

- **recall@6** is how often the right page was among the 6 the model would be shown (`--k` changes the 6).
- **MRR** is how high it ranked: 1 for first place, 0.5 for second, and so on.
- Each miss is listed with what came back instead. (Here the wiki has no note about rice, so the miss is correct.)

Two flags add model calls:

```bash
sb eval --rewrite
```

rewrites each question into search terms first (one call each), and

```bash
sb eval --answers
```

also runs `sb ask` on each question and adds a line such as `Answers: grounded 100%, cites the expected page 94%`. It is slow because it uses the `ask` model.

Write 10 to 20 real questions you would ask; one question moves the percentages a lot. Keep the file: it is how you notice that a change made things worse.

## What is logged

Every `sb ask` appends a line to `.esbi/asks.jsonl`: the question, the pages retrieved, the pages cited, whether it was grounded, tokens and seconds. It stays on your machine.

## Email and cloud models

If the model that answers sends text out (an API, your subscription, a remote server), pages made from email, and the email sections of shared pages, are left out of what it sees. The rules are in [Safety and privacy](../explanation/safety-and-privacy.md#email-stays-local).
