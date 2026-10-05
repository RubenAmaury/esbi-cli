import { describe, expect, it } from 'vitest';
import type { StatusInfo } from '../src/contract';
import { initialRun } from '../src/run-state';
import { statusText } from '../src/status';

const status = (q: Partial<StatusInfo['queue']>): StatusInfo => ({
	vault: '/v',
	queue: { queued: 0, processing: 0, done: 10, failed: 0, ...q },
	failed: [],
});
const idle = { ready: true, run: null, running: false, failedToRead: false, otherVault: false };

describe('statusText', () => {
	it('shows the queue counts', () => {
		expect(statusText({ ...idle, status: status({ queued: 3, failed: 1 }) })).toBe('esbi: 3 queued, 1 failed');
		expect(statusText({ ...idle, status: status({ processing: 1 }) })).toBe('esbi: 1 in progress');
		expect(statusText({ ...idle, status: status({}) })).toBe('esbi: queue empty');
	});
	it('shows run progress while running, counting the source in flight', () => {
		const run = { ...initialRun, queued: 5, done: [{ target: 'a', title: 'a' }], failed: [{ target: 'b', title: 'b' }] };
		expect(statusText({ ...idle, status: null, run, running: true })).toBe('esbi: running 3/5');
		expect(statusText({ ...idle, status: null, run: { ...initialRun }, running: true })).toBe('esbi: running');
	});
	it('says so when sb is not set up or status could not be read', () => {
		expect(statusText({ ...idle, ready: false, status: null })).toBe('esbi: not set up');
		expect(statusText({ ...idle, status: null, failedToRead: true })).toBe('esbi: status unavailable');
	});
});

describe('statusText with a vault mismatch', () => {
	it('says sb uses another vault instead of the queue counts of the wrong vault', () => {
		expect(statusText({ ...idle, status: status({ queued: 3 }), otherVault: true })).toBe('esbi: sb uses another vault');
	});
	it('still shows a run that is going, and "not set up" wins over everything', () => {
		const run = { ...initialRun, queued: 2 };
		expect(statusText({ ...idle, status: null, run, running: true, otherVault: true })).toBe('esbi: running 1/2');
		expect(statusText({ ...idle, ready: false, status: null, otherVault: true })).toBe('esbi: not set up');
	});
});
