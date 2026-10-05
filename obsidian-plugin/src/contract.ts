import type { JsonObject } from './jsonl';

/** The `--json` contract number this plugin understands (see the esbi-cli JSON contract). */
export const PLUGIN_CONTRACT = 1;

export type SbErrorKind =
	| 'missing' // sb is not there (shell exit 126/127)
	| 'old' // sb is installed but has no --json
	| 'too_new' // sb speaks a newer contract than this plugin
	| 'failed' // sb answered with {"error": ...}
	| 'bad_output' // the answer was not JSON, or not a contract object
	| 'timeout'
	| 'spawn'; // the login shell could not be started

export class SbError extends Error {
	constructor(
		readonly kind: SbErrorKind,
		message: string,
		readonly code?: string,
	) {
		super(message);
		this.name = 'SbError';
	}
}

export interface VersionInfo {
	version: string;
	contract: number;
}

export interface Counts {
	queued: number;
	processing: number;
	done: number;
	failed: number;
}

export interface FailedItem {
	target: string;
	attempts: number;
	error: string;
}

export interface StatusInfo {
	vault: string;
	queue: Counts;
	failed: FailedItem[];
}

export interface InfoInfo {
	vault: string;
	version: string;
	/** The config.toml sb is using. */
	config: string;
	/** Model of each task, "<provider>/<name>" (summarize, synthesize, private, ask, ...). */
	models: Record<string, string>;
}

export interface DoctorCheck {
	level: string; // "ok" | "WARN" | "FAIL"
	name: string;
	text: string;
	fix: string;
}

export interface DoctorInfo {
	ok: boolean;
	checks: DoctorCheck[];
}

export interface AddInfo {
	queued: number;
	alreadyKnown: number;
}

export interface AskInfo {
	answer: string;
	cited: string[];
	refused: boolean;
}

const str = (v: unknown, d = ''): string => (typeof v === 'string' ? v : d);
const num = (v: unknown, d = 0): number => (typeof v === 'number' && Number.isFinite(v) ? v : d);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const obj = (v: unknown): JsonObject => (typeof v === 'object' && v !== null ? (v as JsonObject) : {});

// Unknown fields are ignored and missing ones get a default, so an additive CLI change never breaks the plugin.
export const parseVersion = (o: JsonObject): VersionInfo => ({ version: str(o.version, 'unknown'), contract: num(o.contract) });

export const parseStatus = (o: JsonObject): StatusInfo => {
	const q = obj(o.queue);
	return {
		vault: str(o.vault),
		queue: { queued: num(q.queued), processing: num(q.processing), done: num(q.done), failed: num(q.failed) },
		failed: arr(o.failed).map((f) => ({ target: str(obj(f).target), attempts: num(obj(f).attempts), error: str(obj(f).error) })),
	};
};

export const parseInfo = (o: JsonObject): InfoInfo => ({
	vault: str(o.vault),
	version: str(o.version),
	config: str(o.config),
	models: Object.fromEntries(Object.entries(obj(o.models)).filter((e): e is [string, string] => typeof e[1] === 'string')),
});

export const parseDoctor = (o: JsonObject): DoctorInfo => ({
	ok: o.ok === true,
	checks: arr(o.checks).map((c) => ({
		level: str(obj(c).level, 'WARN'),
		name: str(obj(c).name),
		text: str(obj(c).text),
		fix: str(obj(c).fix),
	})),
});

export const parseAdd = (o: JsonObject): AddInfo => ({ queued: num(o.queued), alreadyKnown: num(o.already_known) });

export const parseAsk = (o: JsonObject): AskInfo => ({
	answer: str(o.answer),
	cited: arr(o.cited).filter((c): c is string => typeof c === 'string'),
	refused: o.refused === true,
});
