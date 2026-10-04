import { spawn } from 'child_process';
import { StringDecoder } from 'string_decoder';
import { LineSplitter } from './jsonl';

/** A macOS app started from the Dock has PATH=/usr/bin:/bin:/usr/sbin:/sbin: a login shell restores the user's PATH. */
export function loginShell(platform: string = process.platform): { file: string; args: string[] } {
	// "$0" is the first argument after the script: it never goes through shell parsing.
	return { file: platform === 'darwin' ? '/bin/zsh' : '/bin/sh', args: ['-lc', 'exec "$0" "$@"'] };
}

export interface SbSpawn {
	/** Absolute path to sb, or plain `sb` to let the login shell find it. */
	sbPath: string;
	/** Arguments, passed as an array. Put user text after `--`. */
	args: string[];
	cwd?: string;
	/** Added to the inherited environment. */
	env?: Record<string, string>;
	/** Stop (SIGINT, then SIGTERM) after this long. */
	timeoutMs?: number;
	/** Time between SIGINT and SIGTERM. */
	graceMs?: number;
	/** Aborting cancels the process like job.cancel(). */
	signal?: AbortSignal;
	/** Called for each complete stdout line as it arrives. Without it, lines are collected in the result. */
	onLine?: (line: string) => void;
	/** Test seam. */
	shell?: { file: string; args: string[] };
}

export interface SbResult {
	code: number | null;
	signal: string | null;
	stdoutLines: string[];
	stderrTail: string;
	canceled: boolean;
	timedOut: boolean;
	/** The process could not be started at all. */
	spawnError?: string;
}

export interface SbJob {
	result: Promise<SbResult>;
	/** SIGINT, then SIGTERM after the grace period. Safe to call twice or after the end. */
	cancel: () => void;
}

const STDERR_TAIL_CHARS = 4000;
const DEFAULT_GRACE_MS = 5000;

export function startSb(o: SbSpawn): SbJob {
	const shell = o.shell ?? loginShell();
	const stdoutLines: string[] = [];
	let stderrTail = '';
	let canceled = false;
	let timedOut = false;
	let ended = false;
	let timers: number[] = [];

	let child: ReturnType<typeof spawn>;
	try {
		child = spawn(shell.file, [...shell.args, o.sbPath, ...o.args], {
			cwd: o.cwd,
			env: { ...process.env, PYTHONUNBUFFERED: '1', ...o.env },
			stdio: ['ignore', 'pipe', 'pipe'],
			shell: false,
			windowsHide: true,
		});
	} catch (e) {
		const spawnError = e instanceof Error ? e.message : String(e);
		const result = { code: null, signal: null, stdoutLines, stderrTail, canceled, timedOut, spawnError };
		return { result: Promise.resolve(result), cancel: () => undefined };
	}

	const cancel = (): void => {
		if (ended || canceled) return;
		canceled = true;
		child.kill('SIGINT');
		timers.push(
			window.setTimeout(() => {
				if (!ended) child.kill('SIGTERM');
			}, o.graceMs ?? DEFAULT_GRACE_MS),
		);
	};
	if (o.signal?.aborted) cancel();
	else o.signal?.addEventListener('abort', cancel, { once: true });
	if (o.timeoutMs) {
		timers.push(
			window.setTimeout(() => {
				timedOut = true;
				cancel();
			}, o.timeoutMs),
		);
	}

	const result = new Promise<SbResult>((resolve) => {
		const decoder = new StringDecoder('utf8'); // keeps a character split across two chunks intact
		const splitter = new LineSplitter();
		const emit = (lines: string[]): void => {
			for (const line of lines) {
				if (o.onLine) o.onLine(line);
				else stdoutLines.push(line);
			}
		};
		child.stdout?.on('data', (chunk: Buffer) => emit(splitter.push(decoder.write(chunk))));
		child.stderr?.on('data', (chunk: Buffer) => {
			stderrTail = (stderrTail + chunk.toString('utf8')).slice(-STDERR_TAIL_CHARS);
		});
		const finish = (code: number | null, signal: string | null, spawnError?: string): void => {
			if (ended) return;
			ended = true;
			timers.forEach((t) => window.clearTimeout(t));
			timers = [];
			emit(splitter.push(decoder.end()));
			emit(splitter.flush());
			resolve({ code, signal, stdoutLines, stderrTail, canceled, timedOut, spawnError });
		};
		child.on('error', (e) => finish(null, null, e.message));
		child.on('close', (code, signal) => finish(code, signal));
	});

	return { result, cancel };
}
