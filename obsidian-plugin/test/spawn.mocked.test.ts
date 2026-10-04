// child_process is mocked here: these tests pin how the helper calls Node, which the real-process tests cannot see.
import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

class FakeChild extends EventEmitter {
	stdout = new EventEmitter();
	stderr = new EventEmitter();
	kill = vi.fn();
}

const spawnMock = vi.fn();
vi.mock('child_process', () => ({ spawn: (...a: unknown[]) => spawnMock(...a) }));

const { startSb } = await import('../src/spawn');

let child: FakeChild;
beforeEach(() => {
	child = new FakeChild();
	spawnMock.mockReset();
	spawnMock.mockReturnValue(child);
});
afterEach(() => vi.useRealTimers());

describe('startSb with child_process mocked', () => {
	it('spawns the login shell with an argument array, never a shell string', () => {
		startSb({ sbPath: '/u/.local/bin/sb', args: ['add', '--json', '--', 'x; rm -rf ~'], shell: { file: '/bin/zsh', args: ['-lc', 'exec "$0" "$@"'] } });
		const [file, args, opts] = spawnMock.mock.calls[0] as [string, string[], Record<string, unknown>];
		expect(file).toBe('/bin/zsh');
		expect(args).toEqual(['-lc', 'exec "$0" "$@"', '/u/.local/bin/sb', 'add', '--json', '--', 'x; rm -rf ~']);
		expect(opts.shell).toBe(false);
		expect(opts.stdio).toEqual(['ignore', 'pipe', 'pipe']);
	});

	it('keeps a multibyte character that is split across two chunks', async () => {
		const lines: string[] = [];
		const job = startSb({ sbPath: 'sb', args: [], onLine: (l) => lines.push(l) });
		const bytes = Buffer.from('{"title":"日本語"}\n', 'utf8');
		child.stdout.emit('data', bytes.subarray(0, 11)); // cuts inside the second character
		child.stdout.emit('data', bytes.subarray(11));
		child.emit('close', 0, null);
		await job.result;
		expect(lines).toEqual(['{"title":"日本語"}']);
	});

	it('delivers a last line without a newline when the process closes', async () => {
		const job = startSb({ sbPath: 'sb', args: [] });
		child.stdout.emit('data', Buffer.from('{"a":1}'));
		child.emit('close', 0, null);
		expect((await job.result).stdoutLines).toEqual(['{"a":1}']);
	});

	it('sends SIGINT first and SIGTERM only after the grace period', async () => {
		vi.useFakeTimers();
		const job = startSb({ sbPath: 'sb', args: [], graceMs: 5000 });
		job.cancel();
		job.cancel(); // a second click does nothing
		expect(child.kill.mock.calls).toEqual([['SIGINT']]);
		vi.advanceTimersByTime(4999);
		expect(child.kill.mock.calls).toEqual([['SIGINT']]);
		vi.advanceTimersByTime(2);
		expect(child.kill.mock.calls).toEqual([['SIGINT'], ['SIGTERM']]);
		child.emit('close', null, 'SIGTERM');
		expect((await job.result).canceled).toBe(true);
	});

	it('does not send SIGTERM when the process ended during the grace period', async () => {
		vi.useFakeTimers();
		const job = startSb({ sbPath: 'sb', args: [], graceMs: 5000 });
		job.cancel();
		child.emit('close', 130, null);
		await job.result;
		vi.advanceTimersByTime(10000);
		expect(child.kill.mock.calls).toEqual([['SIGINT']]);
	});

	it('marks a timeout and cancels', async () => {
		vi.useFakeTimers();
		const job = startSb({ sbPath: 'sb', args: [], timeoutMs: 1000 });
		vi.advanceTimersByTime(1001);
		expect(child.kill).toHaveBeenCalledWith('SIGINT');
		child.emit('close', 130, null);
		const r = await job.result;
		expect(r.timedOut).toBe(true);
		expect(r.canceled).toBe(true);
	});

	it('turns a spawn error event into a result instead of throwing', async () => {
		const job = startSb({ sbPath: 'sb', args: [] });
		child.emit('error', new Error('spawn /bin/zsh ENOENT'));
		expect((await job.result).spawnError).toContain('ENOENT');
	});

	it('turns a synchronous spawn failure (such as a NUL byte in an argument) into a result', async () => {
		spawnMock.mockImplementation(() => {
			throw new TypeError('The argument must be a string without null bytes');
		});
		const job = startSb({ sbPath: 'sb', args: ['a\0b'] });
		expect((await job.result).spawnError).toContain('null bytes');
		expect(() => job.cancel()).not.toThrow();
	});
});
