# The daily index

`Home.md` links to today's note, `wiki/daily/YYYY-MM-DD.md`. It is regenerated from the vault's state every run, so your ticks are never lost.

The headings follow `[notes].language`; the table gives the English heading, and the Spanish one in brackets.

| Section | Content |
|---|---|
| **Read** (`Leído`) | Sources the worker saw you tick since the last index |
| **Processed today** (`Procesado hoy`) | Every source processed today, as a checkbox with its one-line summary. **Tick it when you have read it** |
| **Tomorrow's queue** (`Cola de mañana`) | How many sources are still queued, and the oldest 20 (by clip title or file name when known, else the URL) |
| **To review** (`Por revisar`) | Review notes (contradictions, `Lint.md`), sources that failed for good, and sources being retried with their attempt number and last error |
| **Revisit** (`Repasar`) | Three older notes, rotating daily |
| **Runs** (`Ejecuciones`) | Today's runs: time, counts, tokens, duration, why it stopped |
| **Statistics** (`Estadísticas`) | Page counts, today's activity, read progress, orphan pages |

Ticking is one-way: a ticked source becomes `status: read` and stays read.

The routine, step by step: [Read your notes and tick what you have read](../how-to/read-your-notes.md). A tick is only read from a line shaped `- [x] [[Source title]]`. `Home.md` links to today's note; between its `<!-- esbi:start -->` and `<!-- esbi:end -->` comments it shows today's link, how many sources are unread, and how many are queued, and the worker rewrites only that block.
