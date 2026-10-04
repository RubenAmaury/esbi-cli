import { describe, expect, it } from 'vitest';
import { applyExit, applyLine, initialRun, runMessage } from '../src/run-state';
import type { SbResult } from '../src/spawn';

const j = (o: object): string => JSON.stringify({ contract: 1, ...o });
const feed = (lines: string[]) => lines.reduce(applyLine, initialRun);
const exit = (o: Partial<SbResult> = {}): SbResult => ({
	code: 0,
	signal: null,
	stdoutLines: [],
	stderrTail: '',
	canceled: false,
	timedOut: false,
	...o,
});

describe('applyLine', () => {
	it('follows a source through its steps to done', () => {
		const t = 'https://e.com/1';
		let s = feed([j({ event: 'started', queued: 2 }), j({ event: 'source_started', target: t, title: 'Año 日本語' })]);
		expect(s.queued).toBe(2);
		expect(s.current).toEqual({ target: t, title: 'Año 日本語', step: null });
		s = applyLine(s, j({ event: 'step', target: t, name: 'chunk', index: 2, total: 6 }));
		expect(s.current?.step).toEqual({ name: 'chunk', index: 2, total: 6 });
		expect(s.current?.title).toBe('Año 日本語');
		s = applyLine(s, j({ event: 'source_done', target: t, title: 'Año 日本語', note: 'wiki/sources/X.md' }));
		expect(s.current).toBeNull();
		expect(s.done).toEqual([{ target: t, title: 'Año 日本語', note: 'wiki/sources/X.md' }]);
	});

	it('records a failed source with its reason', () => {
		const s = feed([j({ event: 'source_failed', target: 'https://e.com/x', attempt: 1, max_attempts: 3, parked: false, reason: 'timeout' })]);
		expect(s.failed[0]).toMatchObject({ target: 'https://e.com/x', reason: 'timeout', parked: false });
	});

	it('ends on the finished event', () => {
		const s = feed([j({ event: 'finished', ingested: 1, failed: 0, skipped: 2, tokens: 5, stopped_by: null })]);
		expect(s.phase).toBe('finished');
		expect(s.summary).toEqual({ ingested: 1, failed: 0, skipped: 2, stoppedBy: null });
		expect(runMessage(s)).toBe('Done: 1 added, 0 failed, 2 skipped.');
	});

	it('ignores garbage, partial JSON and events it does not know', () => {
		const s = feed(['Welcome banner', '{"event":"sta', j({ event: 'something_new', x: 1 }), '[1,2]']);
		expect(s).toEqual(initialRun);
	});

	it('turns a contract error line into a failure', () => {
		const s = feed([j({ error: 'another run is already in progress', code: 'run_locked' })]);
		expect(s.phase).toBe('failed');
		expect(runMessage(s)).toMatch(/already in progress/);
	});
});

describe('applyExit', () => {
	it('says the item was put back only when sb confirmed it was interrupted', () => {
		const withFinished = applyExit(feed([j({ event: 'finished', ingested: 0, failed: 0, skipped: 0, stopped_by: 'interrupted' })]), exit({ code: 130, canceled: true }));
		expect(runMessage(withFinished)).toBe('Cancelled. The item in progress was put back in the queue.');
		const without = applyExit(feed([j({ event: 'started', queued: 1 })]), exit({ code: null, signal: 'SIGTERM', canceled: true }));
		expect(runMessage(without)).toMatch(/recovers it on the next run/);
		expect(without.phase).toBe('finished');
	});

	it('does not call a timeout a cancellation', () => {
		const s = applyExit(initialRun, exit({ code: 130, canceled: true, timedOut: true, stderrTail: 'slow' }));
		expect(s.canceled).toBe(false);
		expect(s.phase).toBe('failed');
	});

	it('fails with the stderr text when sb dies without finishing', () => {
		const s = applyExit(initialRun, exit({ code: 1, stderrTail: 'Traceback: boom\n' }));
		expect(s).toMatchObject({ phase: 'failed', error: 'Traceback: boom' });
	});

	it('says sb is missing for exit 127 and for a spawn error', () => {
		expect(applyExit(initialRun, exit({ code: 127 })).error).toMatch(/not found/);
		expect(applyExit(initialRun, exit({ code: null, spawnError: 'spawn /bin/zsh ENOENT' })).error).toContain('ENOENT');
	});

	it('keeps a finished run finished', () => {
		const s = applyExit(feed([j({ event: 'finished', ingested: 3, failed: 0, skipped: 0, stopped_by: 'budget' })]), exit({ code: 1 }));
		expect(s.phase).toBe('finished');
		expect(runMessage(s)).toBe('Stopped early (budget): 3 added, 0 failed, 0 skipped.');
	});
});
