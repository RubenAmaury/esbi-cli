import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { RunController } from '../src/run-controller';
import { runMessage, type RunState } from '../src/run-state';
import { SbClient } from '../src/sb';
import { ensureFakeSbExecutable, FAKE_SB } from './helpers';

beforeAll(ensureFakeSbExecutable);
afterEach(() => vi.unstubAllEnvs());

const controller = (onEnd = () => undefined) => new RunController(new SbClient(() => ({ sbPath: FAKE_SB, configPath: '' })), onEnd);
const ended = (c: RunController) =>
	new Promise<RunState>((resolve) => {
		const off = c.subscribe((s) => {
			if (!c.active && s.phase !== 'running') {
				off();
				resolve(s);
			} else if (!c.active && s.canceled) {
				off();
				resolve(s);
			}
		});
	});

describe('RunController with the fake sb', () => {
	it('runs a queue and reports each source', async () => {
		const onEnd = vi.fn();
		const c = controller(onEnd);
		const seen: number[] = [];
		c.subscribe((s) => seen.push(s.done.length));
		expect(c.start()).toBe(true);
		await vi.waitFor(() => expect(c.state?.phase).toBe('finished'), { timeout: 10_000 });
		await vi.waitFor(() => expect(c.active).toBe(false));
		expect(c.state?.queued).toBe(2);
		expect(c.state?.done.map((d) => d.title)).toEqual(['Source 1', 'Source 2']);
		expect(Math.max(...seen)).toBe(2);
		expect(runMessage(c.state as RunState)).toBe('Done: 2 added, 0 failed, 0 skipped.');
		expect(onEnd).toHaveBeenCalledTimes(1);
	});

	it('is single-flight: a second start while running does nothing', async () => {
		vi.stubEnv('FAKE_SB_STEP_SECONDS', '0.2');
		const c = controller();
		expect(c.start()).toBe(true);
		expect(c.start()).toBe(false);
		expect(c.active).toBe(true);
		c.cancel();
		await vi.waitFor(() => expect(c.active).toBe(false), { timeout: 10_000 });
	});

	it('cancels with SIGINT and says the item was put back', async () => {
		vi.stubEnv('FAKE_SB_STEP_SECONDS', '0.3');
		vi.stubEnv('FAKE_SB_SOURCES', '5');
		const c = controller();
		const done = ended(c);
		c.start();
		await vi.waitFor(() => expect(c.state?.current).not.toBeNull(), { timeout: 10_000 });
		c.cancel();
		const s = await done;
		expect(s.canceled).toBe(true);
		expect(s.done.length).toBeLessThan(5);
		expect(runMessage(s)).toBe('Cancelled. The item in progress was put back in the queue.');
	});

	it('shows a friendly failure when another run holds the lock', async () => {
		vi.stubEnv('FAKE_SB_BUSY', '1');
		const c = controller();
		c.start();
		await vi.waitFor(() => expect(c.active).toBe(false), { timeout: 10_000 });
		expect(c.state?.phase).toBe('failed');
		expect(runMessage(c.state as RunState)).toMatch(/already in progress/);
	});

	it('can start again after a run ended', async () => {
		const c = controller();
		c.start();
		await vi.waitFor(() => expect(c.active).toBe(false), { timeout: 10_000 });
		expect(c.start()).toBe(true);
		await vi.waitFor(() => expect(c.active).toBe(false), { timeout: 10_000 });
	});
});
