# How it works

```
 you save things                 the worker (sb run)                        you read
 ───────────────                 ──────────────────                        ────────
 Web Clipper → inbox/  ┐
 forwarded email        ├─►  queue ─► fetch & extract ─► LLM writes a  ─►  wiki/ notes + index.md + log.md
 an older notes folder ┘    (SQLite)  (web, PDF, note)   JSON edit plan     wiki/daily/YYYY-MM-DD.md  ◄── start here
```

Three layers, as in Karpathy's design:

- **`raw/`**: the original of every source, never edited.
- **`wiki/`**: notes written and maintained by the worker: one *source* note per source, plus *concept*, *entity* and *synthesis* pages that grow as more sources arrive. You read it in Obsidian; the worker writes it.
- **`SCHEMA.md`**: the conventions the model is given on every run.

Design rules worth knowing:

- **The model never touches your files.** It only returns a JSON "edit plan". The worker validates the plan (drops invented links, rejects wrong-language or malformed output, retries once) and only then writes.
- **Everything is a git commit** in the vault repo (when `git` is installed; it is optional), one per ingested source, so any change can be reviewed or reverted.
- **Risky things go to review, not to the wiki**: contradictions and lint findings become notes under `wiki/review/`. Nothing is merged or deleted silently.
- It works with **small local models** (Ollama) and with cloud models through the same interface.
