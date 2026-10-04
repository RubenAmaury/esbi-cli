# Check the wiki's health

`sb lint` looks for loose ends in the wiki: pages nothing links to, links that lead nowhere, concepts that look duplicated. It only reports. It never edits, merges or deletes anything.

## Run it

```bash
sb lint
```

```
unlinked-mention: 1
near-duplicate: 1
Details in wiki/review/Lint.md
```

With nothing to report it prints `No problems found.` and exits 0. `sb run` runs the same check at the end of every run (`Lint: 2 issues (see wiki/review/Lint.md)`), so you rarely need to run it by hand. It uses no model and takes a moment, even on thousands of pages.

## Read the report

The report is a note, `wiki/review/Lint.md`, and it appears under **To review** in the daily index. It exists only while there is something to fix, and it is rebuilt on every run. Each section lists up to 50 findings, in the language of the rest of the wiki:

```markdown
## Unlinked mentions
- [[Hermann Ebbinghaus]] mentions [[Forgetting Curve]] without linking it

## Possible duplicates
- [[Forgetting Curve]] ≈ [[Hermann Ebbinghaus]]
```

## What each kind means, and what to do

| Kind (section) | Meaning | What to do |
|---|---|---|
| `orphan` (Orphan pages) | No other page links to this one | Link it from a page that should mention it, or ignore it. A brand-new note is an orphan until something links to it |
| `broken-link` (Broken links) | A `[[link]]` to a page that does not exist | Fix the name, create the page, or remove the link. This is what you see after deleting a note that others linked to |
| `missing-field` (Missing fields) | A page without `title` or `summary` in its frontmatter | Add the field. Pages you made by hand usually lack `summary` |
| `unlinked-mention` (Unlinked mentions) | A concept's name appears in a page that does not link to it | Wrap the name in `[[ ]]` where it helps you. Multi-word names match ignoring case and accents; a single word matches only exactly as written |
| `near-duplicate` (Possible duplicates) | Two concepts or entities that look like the same idea (plural or accent variants, a shared alias) | Decide whether they are the same. If so, keep one page, move what matters from the other, delete it and fix the links; the worker never merges for you. If not, ignore it |
| `missing-concept` (Concepts without a page) | A glossary term that two or more source notes define, with no concept or entity page of its own | Create the page if the idea deserves one, or ignore it |

Findings are suggestions, not errors. Fix what you care about and ignore the rest; ignoring them costs nothing, and there is no way to mark a finding "reviewed": it simply shows again until the cause is gone.

## Contradictions

The worker can also ask the model to flag claims that contradict an existing page. It is off by default, because small models flag tenuous ones. To turn it on, set `flag_contradictions = true` under `[run]` and use a stronger model. A flag becomes a note in `wiki/review/` and a `[!warning]` on the page; nothing is changed silently. See [Configuration](../reference/configuration.md#run).
