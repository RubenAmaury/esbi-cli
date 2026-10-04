# What the worker repairs

Small models make predictable mistakes, so the worker fixes what it can instead of failing the source:

- A one-line summary that is a URL, or just repeats the title ("Zettelkasten - Wikipedia"), is replaced by the first sentence of the model's summary (at most 160 characters), with a warning. The source is ingested rather than parked.
- **Entities** (people, organizations, tools) whose name does not appear in the source text are dropped and reported (small models copy names from other pages into unrelated sources). Concepts may be abstractions the text never spells out, so they are not checked.
- Links to pages that do not exist are dropped, a concept named like a source is skipped, answers in English are retried once, and malformed JSON is retried once.
- Legacy links keep the date of the file they were saved in as `captured` in the source note; everything else records the day it was processed.
