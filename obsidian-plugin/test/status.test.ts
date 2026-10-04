import { mkdirSync, symlinkSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { StatusInfo } from '../src/contract';
import { initialRun } from '../src/run-state';
import { sameFolder, statusText } from '../src/status';
import { scratchDir } from './helpers';

const status = (q: Partial<StatusInfo['queue']>): StatusInfo => ({
	vault: '/v',
	queue: { queued: 0, processing: 0, done: 10, failed: 0, ...q },
	failed: [],
});
const idle = { ready: true, run: null, running: false, failedToRead: false };

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

describe('sameFolder', () => {
	it('sees through symlinks and trailing slashes', () => {
		const dir = scratchDir();
		mkdirSync(join(dir, 'vault'));
		symlinkSync(join(dir, 'vault'), join(dir, 'link'));
		expect(sameFolder(join(dir, 'vault'), join(dir, 'link'))).toBe(true);
		expect(sameFolder(join(dir, 'vault') + '/', join(dir, 'vault'))).toBe(true);
		expect(sameFolder(join(dir, 'vault'), join(dir, 'other'))).toBe(false);
	});
});
