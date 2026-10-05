import {
	PLUGIN_CONTRACT,
	SbError,
	parseAdd,
	parseAsk,
	parseDoctor,
	parseInfo,
	parseStatus,
	parseVersion,
	type AddInfo,
	type AskInfo,
	type DoctorInfo,
	type InfoInfo,
	type StatusInfo,
	type VersionInfo,
} from './contract';
import { lastObject, type JsonObject } from './jsonl';
import { startSb, type SbJob, type SbResult } from './spawn';

export interface SbSettings {
	/** Absolute path to sb, or empty to let the login shell find `sb`. */
	sbPath: string;
	/** Optional config.toml, passed as --config. */
	configPath: string;
	/** Working directory for sb: the vault folder. */
	cwd?: string;
}

const SHORT_TIMEOUT_MS = 30_000;
const ASK_TIMEOUT_MS = 300_000;

interface CallOptions {
	/** Positional arguments (user text). They always go after `--`. */
	positional?: string[];
	/** `version` takes no --config; every other command does. */
	useConfig?: boolean;
	timeoutMs?: number;
	signal?: AbortSignal;
}

/** Turns a finished process into the one JSON object it printed, or a typed error. */
export function interpret(r: SbResult): JsonObject {
	if (r.spawnError) throw new SbError('spawn', r.spawnError);
	const o = lastObject(r.stdoutLines);
	if (o) {
		if (typeof o.contract !== 'number') throw new SbError('bad_output', 'The answer has no contract number.');
		if (o.contract > PLUGIN_CONTRACT) {
			throw new SbError('too_new', `esbi-cli speaks contract ${o.contract}; this plugin understands ${PLUGIN_CONTRACT}.`);
		}
		if (typeof o.error === 'string') {
			throw new SbError('failed', o.error, typeof o.code === 'string' ? o.code : undefined);
		}
		return o; // `sb doctor` exits 1 when a check fails but still answers: the exit code does not matter here
	}
	if (r.timedOut) throw new SbError('timeout', 'esbi-cli did not answer in time.');
	if (r.code === 126 || r.code === 127) {
		throw new SbError('missing', r.stderrTail.trim() || 'esbi-cli was not found.');
	}
	if (r.code === 2 && /no such (option|command)|usage:/i.test(r.stderrTail)) {
		throw new SbError('old', 'This version of esbi-cli has no --json output.');
	}
	throw new SbError('bad_output', r.stderrTail.trim() || `esbi-cli exited with code ${r.code ?? 'none'} and printed no JSON.`);
}

/** Every call to sb goes through here. */
export class SbClient {
	constructor(private readonly settings: () => SbSettings) {}

	private spawnOptions(sub: string, o: CallOptions, extra: string[] = []) {
		const s = this.settings();
		const args = [sub];
		if (o.useConfig !== false && s.configPath.trim() !== '') args.push('--config', s.configPath.trim());
		args.push('--json', ...extra);
		if (o.positional?.length) args.push('--', ...o.positional);
		return { sbPath: s.sbPath.trim() || 'sb', args, cwd: s.cwd };
	}

	private async call(sub: string, o: CallOptions = {}, extra: string[] = []): Promise<JsonObject> {
		const job = startSb({ ...this.spawnOptions(sub, o, extra), timeoutMs: o.timeoutMs ?? SHORT_TIMEOUT_MS, signal: o.signal });
		return interpret(await job.result);
	}

	async version(): Promise<VersionInfo> {
		return parseVersion(await this.call('version', { useConfig: false }));
	}
	async status(): Promise<StatusInfo> {
		return parseStatus(await this.call('status'));
	}
	async info(): Promise<InfoInfo> {
		return parseInfo(await this.call('info'));
	}
	async doctor(): Promise<DoctorInfo> {
		return parseDoctor(await this.call('doctor', { timeoutMs: 120_000 }));
	}
	async add(url: string): Promise<AddInfo> {
		return parseAdd(await this.call('add', { positional: [url] }));
	}
	async ask(question: string, signal?: AbortSignal): Promise<AskInfo> {
		return parseAsk(await this.call('ask', { positional: [question], timeoutMs: ASK_TIMEOUT_MS, signal }));
	}

	/** `sb run --json`: no timeout (a run takes as long as the queue), events arrive through onLine. */
	run(onLine: (line: string) => void): SbJob {
		return startSb({ ...this.spawnOptions('run', {}), onLine });
	}
}
