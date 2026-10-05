// These tests run the real spawn helper against test/fixtures/fake-sb through the real login shell.
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';
import { parseObject } from '../src/jsonl';
import { loginShell, startSb } from '../src/spawn';
import { ensureFakeSbExecutable, FAKE_SB, readArgv, scratchDir } from './helpers';

beforeAll(ensureFakeSbExecutable);

describe('loginShell', () => {
	it('uses zsh on macOS and sh elsewhere, always a login shell that execs its first argument', () => {
		expect(loginShell('darwin').file).toBe('/bin/zsh');
		expect(loginShell('linux').file).toBe('/bin/sh');
		expect(loginShell('darwin').args).toEqual(['-lc', 'exec "$0" "$@"']);
		expect(loginShell('linux').args).toEqual(['-lc', 'exec "$0" "$@"']);
	});
});

describe('startSb with a real login shell', () => {
	it('runs sb and collects the JSON lines', async () => {
		const r = await startSb({ sbPath: FAKE_SB, args: ['version', '--json'] }).result;
		expect(r.code).toBe(0);
		expect(parseObject(r.stdoutLines.at(-1) ?? '')).toEqual({ contract: 1, version: '0.3.0' });
	});

	it('cannot be made to run commands through note titles or URLs', async () => {
		const dir = scratchDir();
		const argvFile = join(dir, 'argv');
		const canary = join(dir, 'pwned');
		const hostile = [
			`https://e.com/"; touch ${canary}; echo "`,
			`$(touch ${canary})`,
			`\`touch ${canary}\``,
			`it's a 'title' with ; & | > < * ? $HOME \\ and "quotes"`,
			'line one\nline two; touch ' + canary,
			'-rf',
			'Año 日本語 🙂',
		];
		const r = await startSb({
			sbPath: FAKE_SB,
			args: ['add', '--json', '--', ...hostile],
			env: { FAKE_SB_ARGV_FILE: argvFile },
		}).result;
		expect(r.code).toBe(0);
		expect(readArgv(argvFile)).toEqual(['add', '--json', '--', ...hostile]);
		expect(existsSync(canary)).toBe(false);
	});

	it('does not run a shell command hidden in the sb path either', async () => {
		const dir = scratchDir();
		const canary = join(dir, 'pwned');
		const r = await startSb({ sbPath: `/nonexistent/sb; touch ${canary}`, args: ['version'] }).result;
		expect(r.code).not.toBe(0);
		expect(existsSync(canary)).toBe(false);
	});

	it('reports a missing sb as exit 127 with the shell message on stderr', async () => {
		const r = await startSb({ sbPath: '/nonexistent/dir/sb', args: ['version'] }).result;
		expect(r.code).toBe(127);
		expect(r.stderrTail).not.toBe('');
	});

	it('streams lines while the process is still running', async () => {
		const seen: string[] = [];
		let finishedWhenFirstLineArrived: boolean | null = null;
		let finished = false;
		const job = startSb({
			sbPath: FAKE_SB,
			args: ['run', '--json'],
			env: { FAKE_SB_STEP_SECONDS: '0.1' },
			onLine: (l) => {
				finishedWhenFirstLineArrived ??= finished;
				seen.push(l);
			},
		});
		const r = await job.result;
		finished = true;
		expect(finishedWhenFirstLineArrived).toBe(false);
		expect(seen.length).toBeGreaterThan(5);
		expect(r.stdoutLines).toEqual([]); // streamed, not buffered
		expect(parseObject(seen.at(-1) ?? '')?.event).toBe('finished');
	});

	it('cancels with SIGINT and lets sb say it was interrupted', async () => {
		const seen: string[] = [];
		let job: ReturnType<typeof startSb> | undefined;
		job = startSb({
			sbPath: FAKE_SB,
			args: ['run', '--json'],
			env: { FAKE_SB_STEP_SECONDS: '0.3', FAKE_SB_SOURCES: '5' },
			onLine: (l) => {
				seen.push(l);
				if (seen.length === 2) job?.cancel();
			},
		});
		const r = await job.result;
		expect(r.canceled).toBe(true);
		expect(r.timedOut).toBe(false);
		expect(r.code).toBe(130);
		expect(r.signal).toBeNull(); // sb handled SIGINT itself: no SIGTERM was needed
		expect(parseObject(seen.at(-1) ?? '')).toMatchObject({ event: 'finished', stopped_by: 'interrupted' });
	});

	it('escalates to SIGTERM when sb ignores SIGINT', async () => {
		let job: ReturnType<typeof startSb> | undefined;
		let cancelled = false;
		job = startSb({
			sbPath: FAKE_SB,
			args: ['run', '--json'],
			env: { FAKE_SB_STEP_SECONDS: '0.3', FAKE_SB_SOURCES: '5', FAKE_SB_IGNORE_INT: '1' },
			graceMs: 300,
			onLine: () => {
				if (!cancelled) {
					cancelled = true;
					job?.cancel();
				}
			},
		});
		const r = await job.result;
		expect(r.canceled).toBe(true);
		expect(r.signal).toBe('SIGTERM');
	});

	it('stops a run that exceeds the timeout', async () => {
		const r = await startSb({
			sbPath: FAKE_SB,
			args: ['run', '--json'],
			env: { FAKE_SB_STEP_SECONDS: '0.3', FAKE_SB_SOURCES: '5' },
			timeoutMs: 400,
		}).result;
		expect(r.timedOut).toBe(true);
		expect(r.code).toBe(130);
	});

	it('cancels when its AbortSignal fires, and at once when it was aborted before the start', async () => {
		const ac = new AbortController();
		const job = startSb({ sbPath: FAKE_SB, args: ['run', '--json'], env: { FAKE_SB_STEP_SECONDS: '0.3', FAKE_SB_SOURCES: '5' }, signal: ac.signal });
		setTimeout(() => ac.abort(), 300);
		const r = await job.result;
		expect(r.canceled).toBe(true);
		expect(r.code).toBe(130);
		const early = await startSb({ sbPath: FAKE_SB, args: ['run', '--json'], env: { FAKE_SB_STEP_SECONDS: '0.3', FAKE_SB_SOURCES: '5' }, signal: AbortSignal.abort() }).result;
		expect(early.canceled).toBe(true);
	});

	it('cancel after the process ended is a no-op', async () => {
		const job = startSb({ sbPath: FAKE_SB, args: ['version', '--json'] });
		await job.result;
		expect(() => job.cancel()).not.toThrow();
	});
});
