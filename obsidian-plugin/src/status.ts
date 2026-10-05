import { existsSync, realpathSync } from 'fs';
import { resolve } from 'path';
import type { StatusInfo } from './contract';
import type { RunState } from './run-state';

/** The status bar text: the run while one is going, else the queue counts, else why there is nothing to show. */
export function statusText(input: { ready: boolean; status: StatusInfo | null; run: RunState | null; running: boolean; failedToRead: boolean }): string {
	if (!input.ready) return 'esbi: not set up';
	if (input.running) {
		const r = input.run;
		const total = r?.queued ?? 0;
		const finished = (r?.done.length ?? 0) + (r?.failed.length ?? 0);
		return total > 0 ? `esbi: running ${Math.min(finished + 1, total)}/${total}` : 'esbi: running';
	}
	if (input.failedToRead || !input.status) return 'esbi: status unavailable';
	const q = input.status.queue;
	const parts: string[] = [];
	if (q.queued > 0) parts.push(`${q.queued} queued`);
	if (q.processing > 0) parts.push(`${q.processing} in progress`);
	if (q.failed > 0) parts.push(`${q.failed} failed`);
	return `esbi: ${parts.length ? parts.join(', ') : 'queue empty'}`;
}

/** True when both paths are the same folder (resolving symlinks, which iCloud and Homebrew paths often have). */
export function sameFolder(a: string, b: string): boolean {
	const real = (p: string): string => {
		try {
			return existsSync(p) ? realpathSync(p) : resolve(p);
		} catch {
			return resolve(p);
		}
	};
	return real(a) === real(b);
}
