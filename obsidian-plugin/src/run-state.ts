import { parseObject, type JsonObject } from './jsonl';
import type { SbResult } from './spawn';

export interface RunItem {
	target: string;
	title: string;
	note?: string;
	reason?: string;
	/** True when sb gave up on this source (it will not be retried by itself). */
	parked?: boolean;
}

export interface RunStep {
	name: string;
	index: number;
	total: number;
}

export interface RunSummary {
	ingested: number;
	failed: number;
	skipped: number;
	stoppedBy: string | null;
}

export interface RunState {
	phase: 'running' | 'finished' | 'failed';
	queued: number;
	current: { target: string; title: string; step: RunStep | null } | null;
	done: RunItem[];
	failed: RunItem[];
	summary: RunSummary | null;
	error: string | null;
	canceled: boolean;
}

export const initialRun: RunState = {
	phase: 'running',
	queued: 0,
	current: null,
	done: [],
	failed: [],
	summary: null,
	error: null,
	canceled: false,
};

const str = (v: unknown, d = ''): string => (typeof v === 'string' ? v : d);
const num = (v: unknown, d = 0): number => (typeof v === 'number' && Number.isFinite(v) ? v : d);

function reduceEvent(s: RunState, e: JsonObject): RunState {
	switch (e.event) {
		case 'started':
			return { ...s, queued: num(e.queued) };
		case 'source_started':
			return { ...s, current: { target: str(e.target), title: str(e.title, str(e.target)), step: null } };
		case 'step':
			return {
				...s,
				current: {
					target: str(e.target),
					title: s.current && s.current.target === e.target ? s.current.title : str(e.target),
					step: { name: str(e.name, 'working'), index: num(e.index), total: num(e.total) },
				},
			};
		case 'source_done':
			return {
				...s,
				current: null,
				done: [...s.done, { target: str(e.target), title: str(e.title, str(e.target)), note: str(e.note) }],
			};
		case 'source_failed':
			return {
				...s,
				current: null,
				failed: [
					...s.failed,
					{ target: str(e.target), title: str(e.title, str(e.target)), reason: str(e.reason), parked: e.parked === true },
				],
			};
		case 'finished':
			return {
				...s,
				current: null,
				phase: 'finished',
				summary: {
					ingested: num(e.ingested),
					failed: num(e.failed),
					skipped: num(e.skipped),
					stoppedBy: typeof e.stopped_by === 'string' ? e.stopped_by : null,
				},
			};
		default:
			return s; // an event added by a newer sb: ignore it
	}
}

/** Apply one stdout line. Anything that is not a JSON object is ignored (shell banners, partial output). */
export function applyLine(s: RunState, line: string): RunState {
	const e = parseObject(line);
	if (!e) return s;
	if (typeof e.error === 'string') return { ...s, phase: 'failed', error: e.error, current: null };
	return reduceEvent(s, e);
}

/** Apply the end of the process: decides between finished, cancelled and failed. */
export function applyExit(s: RunState, r: SbResult): RunState {
	const canceled = r.canceled && !r.timedOut;
	if (s.phase === 'finished' || s.phase === 'failed') return { ...s, canceled, current: null };
	if (canceled) return { ...s, phase: 'finished', canceled, current: null };
	let error: string;
	if (r.spawnError) error = r.spawnError;
	else if (r.code === 126 || r.code === 127) error = 'esbi-cli was not found. Check the path in the plugin settings.';
	else error = r.stderrTail.trim() || `esbi-cli stopped with exit code ${r.code ?? 'none'}.`;
	return { ...s, phase: 'failed', error, current: null };
}

/** One sentence for the end of a run. */
export function runMessage(s: RunState): string {
	if (s.phase === 'failed') {
		const e = s.error ?? 'The run failed.';
		return /lock|already|in progress/i.test(e)
			? 'A run is already in progress (maybe the nightly run). Try again when it ends.'
			: e;
	}
	if (s.canceled) {
		return s.summary?.stoppedBy === 'interrupted'
			? 'Cancelled. The item in progress was put back in the queue.'
			: 'Cancelled. If an item was in progress, esbi-cli recovers it on the next run.';
	}
	if (s.phase === 'finished' && s.summary) {
		const { ingested, failed, skipped, stoppedBy } = s.summary;
		const counts = `${ingested} added, ${failed} failed, ${skipped} skipped.`;
		return stoppedBy ? `Stopped early (${stoppedBy}): ${counts}` : `Done: ${counts}`;
	}
	return 'Running.';
}
