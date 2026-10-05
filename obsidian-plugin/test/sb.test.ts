// The client against the fake sb fixture, through the real login shell.
import { join } from 'node:path';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { SbError } from '../src/contract';
import { SbClient, interpret } from '../src/sb';
import { ensureFakeSbExecutable, FAKE_SB, readArgv, scratchDir } from './helpers';

beforeAll(ensureFakeSbExecutable);
afterEach(() => vi.unstubAllEnvs());

function clientWith(env: Record<string, string>, extra: { configPath?: string; sbPath?: string } = {}) {
	// The fixture reads its knobs from the environment of this process: set them for the child.
	for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v);
	return new SbClient(() => ({ sbPath: extra.sbPath ?? FAKE_SB, configPath: extra.configPath ?? '' }));
}

describe('SbClient', () => {
	it('reads the version and contract', async () => {
		expect(await clientWith({}).version()).toEqual({ version: '0.3.0', contract: 1 });
	});

	it('reads status, info, doctor and add', async () => {
		const c = clientWith({});
		expect((await c.status()).queue).toEqual({ queued: 3, processing: 0, done: 34, failed: 1 });
		expect((await c.info()).vault).toBe('/vault');
		expect((await c.doctor()).ok).toBe(true);
		expect(await c.add('https://example.com/a')).toEqual({ queued: 1, alreadyKnown: 0 });
	});

	it('reports a failing doctor as data, not as an error, although sb exits 1', async () => {
		const d = await clientWith({ FAKE_SB_DOCTOR_FAIL: '1' }).doctor();
		expect(d.ok).toBe(false);
		expect(d.checks[1]).toMatchObject({ level: 'FAIL', fix: 'Start Ollama: ollama serve' });
	});

	it('skips shell-profile noise printed before the JSON', async () => {
		expect((await clientWith({ FAKE_SB_BANNER: '1' }).version()).contract).toBe(1);
	});

	it('refuses a contract newer than the plugin understands', async () => {
		const e = await clientWith({ FAKE_SB_CONTRACT: '2' }).version().catch((x: unknown) => x);
		expect(e).toBeInstanceOf(SbError);
		expect((e as SbError).kind).toBe('too_new');
	});

	it('refuses a newer contract on every command, not only on version', async () => {
		const e = await clientWith({ FAKE_SB_CONTRACT: '9' }).status().catch((x: unknown) => x);
		expect((e as SbError).kind).toBe('too_new');
	});

	it('tells an sb without --json from a missing sb', async () => {
		const old = await clientWith({ FAKE_SB_OLD: '1' }).version().catch((x: unknown) => x);
		expect((old as SbError).kind).toBe('old');
		const missing = await clientWith({}, { sbPath: '/nonexistent/dir/sb' }).version().catch((x: unknown) => x);
		expect((missing as SbError).kind).toBe('missing');
	});

	it('turns a contract error object into a failed error with its code', async () => {
		const e = await clientWith({ FAKE_SB_ERROR: '1' }).status().catch((x: unknown) => x);
		expect(e).toMatchObject({ kind: 'failed', message: 'vault not found', code: 'vault_missing' });
	});

	it('passes --config only where sb accepts it, and user text only after --', async () => {
		const argvFile = join(scratchDir(), 'argv');
		const c = clientWith({ FAKE_SB_ARGV_FILE: argvFile }, { configPath: '/c/my config.toml' });
		await c.version();
		expect(readArgv(argvFile)).toEqual(['version', '--json']);
		await c.status();
		expect(readArgv(argvFile)).toEqual(['status', '--config', '/c/my config.toml', '--json']);
		await c.ask('-v; what is $(x)?');
		expect(readArgv(argvFile)).toEqual(['ask', '--config', '/c/my config.toml', '--json', '--', '-v; what is $(x)?']);
		await c.add('https://e.com/?a=1&b=2');
		expect(readArgv(argvFile)).toEqual(['add', '--config', '/c/my config.toml', '--json', '--', 'https://e.com/?a=1&b=2']);
	});

	it('reads an answer with its cited pages', async () => {
		const a = await clientWith({}).ask('what is an agent harness?');
		expect(a.cited).toEqual(['Agent harness', 'Tool use']);
		expect(a.refused).toBe(false);
		expect(a.answer).toContain('[[Agent harness]]');
	});
});

describe('interpret', () => {
	const base = { code: 0, signal: null, stderrTail: '', canceled: false, timedOut: false };
	it('says bad_output for non-JSON stdout', () => {
		expect(() => interpret({ ...base, code: 1, stdoutLines: ['Traceback...'], stderrTail: 'boom' })).toThrow(/boom/);
	});
	it('says bad_output for JSON without a contract number', () => {
		expect(() => interpret({ ...base, stdoutLines: ['{"version":"0.2.0"}'] })).toThrow(SbError);
	});
	it('maps a timeout', () => {
		const run = () => interpret({ ...base, code: 130, timedOut: true, stdoutLines: [] });
		expect(run).toThrow(expect.objectContaining({ kind: 'timeout' }));
	});
});
